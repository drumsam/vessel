import argparse
import importlib
import json
from .api.server import make_server
from .auction_import.importer import import_auction
from .collectors.runner import refresh
from .observations.store import Store


def main():
    parser = argparse.ArgumentParser(description="VESSEL market evidence")
    parser.add_argument("--db", default="var/market-data.sqlite3")
    parser.add_argument("--resolver", help="Canonical resolver factory as module:callable; omitted means unresolved only")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("resolve-pending")
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=8765)
    auction = sub.add_parser("import-auction")
    auction.add_argument("path")
    auction.add_argument("--source", required=True)
    collect = sub.add_parser("refresh")
    collect.add_argument("--collector", action="append", default=[], help="Adapter factory as module:callable")
    args = parser.parse_args()

    def load(spec):
        module, name = spec.split(":", 1)
        return getattr(importlib.import_module(module), name)()

    store = Store(args.db, load(args.resolver) if args.resolver else None)
    if args.command == "serve":
        httpd = make_server(store, port=args.port)
        print(f"Internal evidence API listening on loopback port {args.port}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
    elif args.command == "import-auction":
        result = import_auction(store, args.path, args.source)
        print(json.dumps(result, indent=2))
        if result["status"] != "SUCCEEDED":
            raise SystemExit(1)
    elif args.command == "resolve-pending":
        print(json.dumps({"resolved": store.resolve_pending()}))
    elif args.command == "refresh":
        if not args.collector:
            parser.error("refresh requires at least one configured --collector module:factory")
        result = refresh(store, [load(spec) for spec in args.collector])
        print(json.dumps(result, indent=2))
        if any(not r["complete"] for r in result):
            raise SystemExit(1)
    else:
        print(json.dumps({"database": args.db, "status": "initialized"}))


if __name__ == "__main__":
    main()
