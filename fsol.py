!#/env/usr python3
#code touched by @Ox7eck
#contact: https://t.me/Ox7eck
"""
fetch_funded_solana.py
Fetch funded Solana addresses (balance > 0 lamports) using the Solana JSON-RPC API.

Usage:
    python fetch_funded_solana.py --help

Requirements:
    pip install requests

Notes:
    - "Funded" means the account has a lamport balance > 0.
    - You can use a free public RPC or your own (e.g. Helius, QuickNode, Alchemy).
    - getProgramAccounts with memcmp can target token accounts, etc.
    - getLargestAccounts returns the top 20 richest accounts on mainnet.
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

import requests

# ── Default RPC endpoints ──────────────────────────────────────────────────────
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
DEVNET_RPC  = "https://api.devnet.solana.com"
TESTNET_RPC = "https://api.testnet.solana.com"

LAMPORTS_PER_SOL = 1_000_000_000


# ── Low-level RPC helper ───────────────────────────────────────────────────────
def rpc(endpoint: str, method: str, params=None, timeout: int = 30):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }
    resp = requests.post(endpoint, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


# ── Strategy 1: getLargestAccounts ────────────────────────────────────────────
def get_largest_accounts(endpoint: str) -> list[dict]:
    """
    Returns the 20 largest (by SOL balance) non-vote accounts on the network.
    This is the quickest way to get a small set of definitely-funded addresses.
    """
    print("[*] Fetching top-20 largest accounts via getLargestAccounts …")
    result = rpc(endpoint, "getLargestAccounts", [{"filter": "nonCirculatingSupply"}])
    accounts = result.get("value", [])
    funded = []
    for acc in accounts:
        lamports = acc["lamports"]
        funded.append({
            "address": acc["address"],
            "lamports": lamports,
            "sol": lamports / LAMPORTS_PER_SOL,
        })
    return funded


# ── Strategy 2: batch getBalance for a list of addresses ──────────────────────
def check_addresses(endpoint: str, addresses: list[str]) -> list[dict]:
    """
    Given a list of addresses, return only those with balance > 0.
    Useful when you already have candidate addresses (e.g. from a CSV or snapshot).
    """
    print(f"[*] Checking balances for {len(addresses)} address(es) …")
    funded = []
    for addr in addresses:
        try:
            result = rpc(endpoint, "getBalance", [addr])
            lamports = result["value"]
            if lamports > 0:
                funded.append({
                    "address": addr,
                    "lamports": lamports,
                    "sol": lamports / LAMPORTS_PER_SOL,
                })
                print(f"    ✓ {addr}  →  {lamports / LAMPORTS_PER_SOL:.6f} SOL")
            else:
                print(f"    ✗ {addr}  →  0 SOL (unfunded)")
        except Exception as exc:
            print(f"    ! {addr}  →  error: {exc}")
        time.sleep(0.1)  # be polite to public nodes
    return funded


# ── Strategy 3: getProgramAccounts (token program example) ────────────────────
def get_funded_token_accounts(
    endpoint: str,
    program_id: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    min_lamports: int = 1,
    limit: int = 100,
) -> list[dict]:
    """
    Fetches accounts owned by a program (default: SPL Token program) that have
    at least `min_lamports` lamports.  Returns up to `limit` results.

    Warning: getProgramAccounts can be disabled on heavily loaded public nodes.
    Use a dedicated RPC (Helius, QuickNode, etc.) for production use.
    """
    print(f"[*] Fetching program accounts for {program_id} (min {min_lamports} lamports) …")
    params = [
        program_id,
        {
            "encoding": "base64",
            "filters": [
                {"dataSize": 165},  # standard SPL token account size
            ],
        },
    ]
    try:
        accounts = rpc(endpoint, "getProgramAccounts", params)
    except RuntimeError as e:
        print(f"    ! getProgramAccounts failed: {e}")
        print("      Try a paid RPC provider (Helius, QuickNode, Alchemy).")
        return []

    funded = []
    for acc in accounts[:limit]:
        lamports = acc["account"]["lamports"]
        if lamports >= min_lamports:
            funded.append({
                "address": acc["pubkey"],
                "lamports": lamports,
                "sol": lamports / LAMPORTS_PER_SOL,
            })
    return funded


# ── Strategy 4: read addresses from a file ────────────────────────────────────
def load_addresses_from_file(path: str) -> list[str]:
    """One address per line (or a JSON array)."""
    with open(path) as f:
        content = f.read().strip()
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [str(a).strip() for a in data if a]
    except json.JSONDecodeError:
        pass
    return [line.strip() for line in content.splitlines() if line.strip()]


# ── Output helpers ─────────────────────────────────────────────────────────────
def print_table(funded: list[dict]):
    if not funded:
        print("\n  No funded addresses found.")
        return
    print(f"\n{'#':<5} {'Address':<48} {'SOL':>16}")
    print("-" * 72)
    for i, a in enumerate(funded, 1):
        print(f"{i:<5} {a['address']:<48} {a['sol']:>16.6f}")
    total = sum(a["sol"] for a in funded)
    print("-" * 72)
    print(f"{'Total funded addresses:':<54} {len(funded):>4}")
    print(f"{'Total SOL:':<54} {total:>16.6f}\n")


def save_json(funded: list[dict], path: str):
    with open(path, "w") as f:
        json.dump(funded, f, indent=2)
    print(f"[✓] Saved {len(funded)} record(s) to {path}")


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        description="Fetch funded Solana addresses (balance > 0).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Top-20 richest accounts on mainnet:
  python fetch_funded_solana.py --mode largest

  # Check a list of addresses from a file:
  python fetch_funded_solana.py --mode file --input addresses.txt

  # Check specific addresses inline:
  python fetch_funded_solana.py --mode check \\
      --addresses So11111111111111111111111111111111111111112 \\
                  11111111111111111111111111111111

  # Token program accounts (requires a paid RPC):
  python fetch_funded_solana.py --mode program --rpc https://rpc.helius.xyz/?api-key=YOUR_KEY

  # Use devnet:
  python fetch_funded_solana.py --mode largest --network devnet
""",
    )
    p.add_argument(
        "--mode",
        choices=["largest", "check", "file", "program"],
        default="largest",
        help="Strategy: largest | check | file | program  (default: largest)",
    )
    p.add_argument(
        "--network",
        choices=["mainnet", "devnet", "testnet"],
        default="mainnet",
        help="Solana network  (default: mainnet)",
    )
    p.add_argument("--rpc", default=None, help="Override RPC endpoint URL")
    p.add_argument("--addresses", nargs="+", metavar="ADDR", help="Addresses for --mode check")
    p.add_argument("--input", metavar="FILE", help="Path to address list for --mode file")
    p.add_argument("--output", metavar="FILE", default=None, help="Save results to JSON file")
    p.add_argument(
        "--program-id",
        default="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        help="Program ID for --mode program",
    )
    p.add_argument(
        "--min-lamports", type=int, default=1, help="Min lamports for --mode program"
    )
    p.add_argument(
        "--limit", type=int, default=100, help="Max accounts for --mode program"
    )
    return p.parse_args()


def main():
    args = parse_args()

    # Resolve endpoint
    network_map = {
        "mainnet": DEFAULT_RPC,
        "devnet":  DEVNET_RPC,
        "testnet": TESTNET_RPC,
    }
    endpoint = args.rpc or network_map[args.network]
    print(f"[*] RPC endpoint: {endpoint}")

    # Run chosen strategy
    if args.mode == "largest":
        funded = get_largest_accounts(endpoint)

    elif args.mode == "check":
        if not args.addresses:
            print("Error: --mode check requires --addresses", file=sys.stderr)
            sys.exit(1)
        funded = check_addresses(endpoint, args.addresses)

    elif args.mode == "file":
        if not args.input:
            print("Error: --mode file requires --input FILE", file=sys.stderr)
            sys.exit(1)
        addresses = load_addresses_from_file(args.input)
        print(f"[*] Loaded {len(addresses)} address(es) from {args.input}")
        funded = check_addresses(endpoint, addresses)

    elif args.mode == "program":
        funded = get_funded_token_accounts(
            endpoint,
            program_id=args.program_id,
            min_lamports=args.min_lamports,
            limit=args.limit,
        )

    else:
        print("Unknown mode", file=sys.stderr)
        sys.exit(1)

    # Display results
    print_table(funded)

    # Optionally save
    if args.output:
        save_json(funded, args.output)
    elif funded:
        default_out = "funded_solana_addresses.json"
        save_json(funded, default_out)


if __name__ == "__main__":
    main()
