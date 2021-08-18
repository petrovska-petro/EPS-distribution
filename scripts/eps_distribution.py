from brownie import Contract, chain, web3, Wei
import json
import time
import datetime
from pathlib import Path
from fractions import Fraction
from collections import defaultdict
import requests
import csv
import numpy as np

# Note: EPS distribution every Thrusday 00:00UTC

# setts and swaps contract involved
setts_entitled = [
    "0x6dEf55d2e18486B9dDfaA075bc4e4EE0B28c1545",
    "0xd04c48A53c111300aD41190D63681ed3dAd998eC",
    "0xb9D076fDe463dbc9f915E5392F807315Bf940334",
    "0x8c76970747afd5398e958bDfadA4cf0B9FcA16c4",
    "0x55912D0Cf83B75c492E761932ABc4DB4a5CB1b17",
    "0xf349c0faA80fC1870306Ac093f75934078e28991",
    "0x5Dce29e92b1b939F8E8C60DcF15BDE82A85be4a9",
    "0xBE08Ef12e4a553666291E9fFC24fCCFd354F2Dd2",
    "0x2B5455aac8d64C14786c3a29858E43b5945819C0",
]
curve_swaps = [
    "0x93054188d876f558f4a66B2EF1d97d16eDf0895B",
    "0x7fC77b5c7614E1533320Ea6DDc2Eb61fa00A9714",
    "0xC25099792E9349C7DD09759744ea681C7de2cb66",
    "0x4CA9b3063Ec5866A4B82E437059D2C43d1be596F",
    "0x7F55DDe206dbAD629C080068923b36fe9D6bDBeF",
    "0xd81dA8D904b52208541Bade1bD6595D8a251F8dd",
    "0x071c661B4DeefB59E2a3DdB20Db036821eeE8F4b",
    "0x80466c64868E1ab14a1Ddf27A676C3fcBE638Fe5"
]
namings = [
    "sett_renCrv",
    "sett_sbtcCrv",
    "sett_tbtcCrv",
    "sett_hbtcCrv",
    "sett_pbtcCrv",
    "sett_obtcCrv",
    "sett_bbtcCrv",
    "sett_tricrypto",
    "sett_cvxCrv",
]

curve_coin_idx = 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# CRV - WETH - WBTC
SWAPPING_PATH = [
    "0xD533a949740bb3306d119CC777fa900bA034cd52",
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
]
sushi_router = "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F"

url = "https://www.convexfinance.com/api/eps/address-airdrop-info?address=0x6DA4c138Dd178F6179091C260de643529A2dAcfe"

last_weeks = [
    "2021-08-05",
    "2021-07-29",
    "2021-07-22",
    "2021-07-15",
    "2021-07-08",
    "2021-07-01",
]

def get_depositors_sett(start_block):
    addresses_dict = {}
    """only run if contract are not recognise -> for asset in setts_entitled:
        Contract.from_explorer(asset)"""

    latest = int(chain[-1].number) - 11000

    for idx, addr in enumerate(setts_entitled):
        token_contract = Contract(addr)
        token = web3.eth.contract(token_contract.address, abi=token_contract.abi)
        addresses = set([])
        for height in range(start_block, latest, 10000):
            print(f"{height}/{latest}")
            # users who receive the receipt of depositing either via proxy-bridge or direct interaction
            addresses.update(
                i.args["to"]
                for i in token.events.Transfer().getLogs(
                    fromBlock=height, toBlock=height + 10000
                )
                if i.args["from"] == ZERO_ADDRESS
            )

        sett_name = namings[idx]
        addresses_dict[sett_name] = sorted(addresses)
        print(f"naming: {namings[idx]}")
        print(f"\nFound {len(addresses)} addresses")

    return addresses_dict, latest


# encapsules for each address the total wbtc they are contributing into the products
def get_receipt_balances(addresses, block):

    """only run if contract are not recognise ->for asset in curve_swaps:
    Contract.from_explorer(asset)"""

    balances_setts = {}
    for idx, name in enumerate(namings):
        sett_receipt = Contract(setts_entitled[idx])
        # will be req to multiply the balanceOf to translate to underlying deposited
        ppfs = sett_receipt.getPricePerFullShare()
        print(f"ppfs: {ppfs}")
        mc_data = [
            [str(sett_receipt), sett_receipt.balanceOf.encode_input(addr)]
            for addr in addresses.get(name)
        ]
        multicall = Contract("0x5e227AD1969Ea493B43F840cfF78d08a6fc17796")

        if name == "sett_cvxCrv":
            router_contract = Contract(sushi_router)
        else:
            print(f"Target {name} and address {curve_swaps[idx]}")
            swap = Contract(curve_swaps[idx])

        balances = {}
        step = 30
        for i in range(0, len(mc_data), step):
            print(f"{i}/{len(mc_data)}")
            response = multicall.aggregate.call(
                mc_data[i : i + step], block_identifier=block
            )[1]
            decoded = [sett_receipt.balanceOf.decode_output(data) for data in response]
            # here we use ppfs to get val of underlying
            decoded = [value * Wei(ppfs / 10 ** 18) for value in decoded]
            if (
                name == "sett_tbtcCrv"
                or name == "sett_pbtcCrv"
                or name == "sett_obtcCrv"
                or name == "sett_bbtcCrv"
            ):
                # needs first to get rate of sbtcCrv then wbtc
                swap_helper = Contract(curve_swaps[1])
                balances.update(
                    {
                        addr.lower(): swap_helper.calc_withdraw_one_coin(
                            swap.calc_withdraw_one_coin(balance, curve_coin_idx),
                            curve_coin_idx,
                        )
                        for addr, balance in zip(
                            addresses.get(name)[i : i + step], decoded
                        )
                        if balance > 0
                    }
                )
            elif name == "sett_cvxCrv":
                balances.update(
                    {
                        addr.lower(): router_contract.getAmountsOut(
                            balance, SWAPPING_PATH
                        )[2]
                        for addr, balance in zip(
                            addresses.get(name)[i : i + step], decoded
                        )
                        if balance > 0
                    }
                )
            else:
                balances.update(
                    {
                        addr.lower(): swap.calc_withdraw_one_coin(
                            balance, curve_coin_idx
                        )
                        for addr, balance in zip(
                            addresses.get(name)[i : i + step], decoded
                        )
                        if balance > 0
                    }
                )

        balances_setts[name] = balances

    # prior to return, sum all of the common keys to generate an unique dict with each addresss contribution
    temp_input = [list(balances_setts[key].items()) for key in balances_setts]
    output = defaultdict(int)
    for d in temp_input:
        for item in d:
            output[item[0]] += item[1]

    return dict(output)


def get_proof(balances, snapshot_block, last_week=1):
    # pick info for endpoint
    response = requests.get(url)
    json_airdrop_data = response.json()["matchedAirdropData"]
    airdrop_data_filtered_none = [
        entry for entry in json_airdrop_data if entry is not None
    ]

    # calc the distribution
    last_week_args = airdrop_data_filtered_none[-last_week]
    total_to_distribute = int(last_week_args["amount"])
    total_contributed = sum(balances.values())

    balances = {
        k: int(Fraction(v * total_to_distribute / total_contributed))
        for k, v in balances.items()
    }
    balances = {k: v for k, v in balances.items() if v}

    elements = [
        (index, account, balances[account])
        for index, account in enumerate(sorted(balances))
    ]

    distribution = {
        "tokenTotal": hex(sum(balances.values())),
        "blockHeight": snapshot_block,
        "claims": {
            user: {"index": index, "amount": hex(amount)}
            for index, user, amount in elements
        },
    }

    return distribution, balances


def get_block_at_timestamp(timestamp):
    current = chain[-1]

    high = current.number - (current.timestamp - timestamp) // 15
    low = current.number - (current.timestamp - timestamp) // 11

    while low <= high:
        middle = low + (high - low) // 2
        block = chain[middle]
        if block.timestamp >= timestamp and chain[middle - 1].timestamp < timestamp:
            return middle
        elif block.timestamp < timestamp:
            low = middle + 1
        else:
            high = middle - 1
    raise ValueError


def takeSecond(elem):
    return elem[1]


def main():
    addresses_json = Path("addresses.json")
    if addresses_json.exists():
        with addresses_json.open() as fp:
            data = json.load(fp)
            start_block = data["latest"]
            addresses = data["addresses"]
    else:
        start_block = 11380872
    #addresses, height = get_depositors_sett(start_block)
    with addresses_json.open("w") as file:
        json.dump({"addresses": addresses, "latest": 13038322}, file)
    
    for num, date in enumerate(last_weeks):
        dt = datetime.datetime.strptime(f"{date} 01:00:00", "%Y-%m-%d %H:%M:%S")
        snapshot_time = int(time.mktime(dt.timetuple()))
        snapshot_block = get_block_at_timestamp(snapshot_time)
        date = time.strftime("%Y-%m-%d", time.gmtime(snapshot_time))

        balances = get_receipt_balances(addresses, snapshot_block)
        balances_json = Path(f"balances_wbtc_denominated/balances-{date}.json")
        with balances_json.open("w") as file:
            json.dump({"balances": balances}, file)
        # specify last arg -> X weeks back time, last week claims by default
        distribution, balances = get_proof(balances, snapshot_block, num + 2)

        distro_json = Path(f"distributions/distribution-{date}.json")
        with distro_json.open("w") as fp:
            json.dump(distribution, fp)

        # generate csv
        r = list(balances.items())
        for idx in range(len(r)):
            # format amount - better visual
            r[idx] = (r[idx][0], r[idx][1] / (10 ** 18))

        r.sort(key=takeSecond, reverse=True)
        array_formatted_distribution = np.array(r)

        csv_file = open(f"distributions_csv/distribution-{date}.csv", "a+", newline="")
        with csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["address", "amount"])
            writer.writeheader()
            write = csv.writer(csv_file)
            write.writerows(array_formatted_distribution)

        print(f"Created json & csv distributions for {date}")
