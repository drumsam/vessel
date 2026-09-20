"""Manage operators. There is no self-service password reset: an admin sets one.

    python scripts/manage_operators.py add alice "Alice Baker" --password ...
    python scripts/manage_operators.py password alice
    python scripts/manage_operators.py disable alice
    python scripts/manage_operators.py enable alice
    python scripts/manage_operators.py list

Omit --password and it is read without echoing.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import auth                      # noqa: E402
from app.db.connection import transaction     # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="create an operator")
    add.add_argument("username")
    add.add_argument("display_name")
    add.add_argument("--password")
    add.add_argument("--note")

    pw = sub.add_parser("password", help="set a password and end that operator's sessions")
    pw.add_argument("username")
    pw.add_argument("--password")

    for name, help_text in (("disable", "revoke access, keeping the history"),
                            ("enable", "restore access")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("username")

    sub.add_parser("list", help="list operators")
    args = parser.parse_args()

    if args.command == "add":
        password = args.password or getpass.getpass("password: ")
        row = auth.create_operator(args.username, args.display_name, password, args.note)
        print("created", row["username"], row["operator_id"])
    elif args.command == "password":
        password = args.password or getpass.getpass("password: ")
        row = auth.set_password(args.username, password)
        print("password set for", row["username"]) if row else sys.exit("no such operator")
    elif args.command in ("disable", "enable"):
        row = auth.set_active(args.username, args.command == "enable")
        print(args.command + "d", row["username"]) if row else sys.exit("no such operator")
    else:
        with transaction() as conn:
            for r in conn.execute(
                    "SELECT username, display_name, active, note FROM operator ORDER BY username"):
                print(f"{'*' if r['active'] else '-'} {r['username']:<20} {r['display_name']:<28}"
                      f" {r['note'] or ''}")


if __name__ == "__main__":
    main()
