"""CLI: python -m whoop {auth-url|login|sync|digest}.

Output of auth-url/login/sync is safe for public CI logs (no tokens, no health data).
"""

import argparse
import os
import sys
import urllib.parse

from . import api, digest, store, sync


def _redirect_uri() -> str:
    return os.environ.get("WHOOP_REDIRECT_URI", "https://github.com/no6hp/WHOOP")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="whoop")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth-url", help="print the WHOOP login link")
    login = sub.add_parser("login", help="exchange the code from the redirect URL for tokens")
    login.add_argument("code", help="the ?code=... value, or the whole redirect URL")
    sub.add_parser("sync", help="fetch new data into the encrypted store")
    dg = sub.add_parser("digest", help="print the analysis digest (contains health data!)")
    dg.add_argument("--mode", choices=["morning", "evening", "weekly"], default="morning")
    args = p.parse_args(argv)

    if args.cmd == "auth-url":
        client_id, _ = sync.credentials()
        print(api.authorization_url(client_id, _redirect_uri()))
    elif args.cmd == "login":
        code = args.code.strip()
        if "code=" in code:
            code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)["code"][0]
        tokens = api.exchange_code(*sync.credentials(), _redirect_uri(), code)
        store.save(store.TOKEN_FILE, tokens)
        print("Login stored (encrypted).")
    elif args.cmd == "sync":
        res = sync.sync()
        print(f"Sync ok - records fetched: {res['fetched']}, changed: {res['changed']}")
    elif args.cmd == "digest":
        db = store.load(store.DATA_FILE)
        if db is None:
            print(f"No data file at {store.DATA_FILE}", file=sys.stderr)
            return 1
        print(digest.build(db, args.mode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
