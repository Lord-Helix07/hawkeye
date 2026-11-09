"""Manage the approved badge list: only badges on it can register or log in.

Run from the backend folder, with AWS credentials for the Hawkeye DynamoDB tables:

    python website/manage_badges.py list
    python website/manage_badges.py generate 100       # make 100 new random badges, approve them, print them
    python website/manage_badges.py generate 100 --out ../approved_badges.txt   # ...and save them to a file
    python website/manage_badges.py add 1234 5678      # approve badges (any email can register them)
    python website/manage_badges.py remove 1234        # blocks registering and new logins for 1234
    python website/manage_badges.py approve-existing   # put every current account's badge on the list

Removing a badge stops new logins right away; someone already logged in stays
in until their login expires (12 hours).
"""

import argparse
import secrets
import sys

from botocore.exceptions import BotoCoreError, ClientError

from users_store import (
    UsersTableSchemaError,
    add_approved_badge,
    list_approved_badges,
    list_users,
    remove_approved_badge,
)


def cmd_list(_args) -> int:
    badges = list_approved_badges()
    registered = {user["badge_num"] for user in list_users()}
    if not badges:
        print("No approved badges yet. Add one with: python website/manage_badges.py add <badge>")
        return 0
    print(f"{'BADGE':<12} STATUS")
    for item in badges:
        status = "registered" if item["badge_num"] in registered else "not registered yet"
        print(f"{item['badge_num']:<12} {status}")
    return 0


def cmd_add(args) -> int:
    for badge in args.badges:
        add_approved_badge(badge)
        print(f"Approved badge {badge.strip()}.")
    return 0


# 8 random digits: 90 million possibilities, so a made-up number is very unlikely to be approved.
BADGE_DIGITS = 8


def new_badge_numbers(count: int, taken: set[str]) -> list[str]:
    """Random badge numbers that aren't in `taken` (or repeated)."""
    low, high = 10 ** (BADGE_DIGITS - 1), 10**BADGE_DIGITS
    badges: list[str] = []
    while len(badges) < count:
        badge = str(low + secrets.randbelow(high - low))
        if badge not in taken:
            taken.add(badge)
            badges.append(badge)
    return badges


def cmd_generate(args) -> int:
    if args.count < 1:
        raise ValueError("count must be at least 1")
    taken = {item["badge_num"] for item in list_approved_badges()}
    taken |= {user["badge_num"] for user in list_users()}
    badges = new_badge_numbers(args.count, taken)
    for badge in badges:
        add_approved_badge(badge)
        print(badge)
    if args.out:
        with open(args.out, "a", encoding="utf-8") as file:
            file.write("".join(f"{badge}\n" for badge in badges))
        print(f"{len(badges)} badge(s) approved and added to {args.out}.", file=sys.stderr)
    else:
        print(f"{len(badges)} badge(s) approved.", file=sys.stderr)
    return 0


def cmd_remove(args) -> int:
    if remove_approved_badge(args.badge):
        print(f"Removed badge {args.badge.strip()}. It can no longer register or log in.")
        return 0
    print(f"Badge {args.badge.strip()} wasn't on the approved list.", file=sys.stderr)
    return 1


def cmd_approve_existing(_args) -> int:
    users = list_users()
    for user in users:
        add_approved_badge(user["badge_num"])
        print(f"Approved {user['badge_num']}")
    print(f"{len(users)} existing account(s) approved.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Manage the Hawkeye approved badge list.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="show approved badges").set_defaults(run=cmd_list)

    add = commands.add_parser("add", help="approve one or more badge numbers")
    add.add_argument("badges", nargs="+", metavar="badge")
    add.set_defaults(run=cmd_add)

    generate = commands.add_parser("generate", help="make new random badge numbers and approve them")
    generate.add_argument("count", type=int)
    generate.add_argument("--out", help="also append the new badges to this file, one per line")
    generate.set_defaults(run=cmd_generate)

    remove = commands.add_parser("remove", help="take a badge off the list")
    remove.add_argument("badge")
    remove.set_defaults(run=cmd_remove)

    commands.add_parser(
        "approve-existing", help="approve every badge that already has an account"
    ).set_defaults(run=cmd_approve_existing)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (BotoCoreError, ClientError, UsersTableSchemaError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
