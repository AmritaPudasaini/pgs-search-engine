"""Create (or reset) an admin account from the command line.

The first SUPER_ADMIN has to come from somewhere: the API cannot create one before
anyone can log in. The password is read without echo and hashed with Argon2id
(`pgs_db.security`); it never appears in shell history or process lists.

Usage:
    python scripts/create_admin.py <username> --email admin@example.gov.np
    python scripts/create_admin.py <username> --role AUDITOR
    python scripts/create_admin.py <username> --reset-password
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from pgs_db import OpsRepository, make_session_factory
from pgs_db.enums import AdminRole
from pgs_db.models import AdminUser
from pgs_db.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("username")
    parser.add_argument("--email")
    parser.add_argument("--role", choices=[r.value for r in AdminRole], default="SUPER_ADMIN")
    parser.add_argument("--reset-password", action="store_true", help="for an existing account")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    with make_session_factory().begin() as session:
        ops = OpsRepository(session)
        existing = session.scalar(
            select(AdminUser).where(AdminUser.username == args.username.strip().lower())
        )
        if args.reset_password:
            if existing is None:
                print(f"No admin named {args.username!r}.", file=sys.stderr)
                return 1
            ops.set_password_hash(existing.id, password_hash)
            ops.set_active(existing.id, True)
            print(f"Password reset for {existing.username}.")
            return 0
        if existing is not None:
            print(f"{existing.username} already exists; use --reset-password.", file=sys.stderr)
            return 1
        user = ops.create_admin(
            args.username, password_hash=password_hash, role=AdminRole(args.role), email=args.email
        )
        print(f"Created {user.role.value} {user.username}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
