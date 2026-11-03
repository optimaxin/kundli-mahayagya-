"""Create the first ADMIN (or any staff) account securely.

The password is never accepted as a command-line argument (it would leak into
shell history and process lists). It is read from an interactive prompt, or
from stdin with --password-stdin (for automation, e.g. from a secrets manager).

Usage:
    python -m scripts.create_admin --email admin@example.org --name "Event Admin"
    printf '%s' "$ADMIN_PASSWORD" | python -m scripts.create_admin --email ... --name ... --password-stdin
    python -m scripts.create_admin --email scan1@example.org --name "Gate 1" --role SCANNER --session 1
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.core.database import get_sessionmaker
from app.core.errors import AppError
from app.core.security import validate_password_strength
from app.models.enums import Role
from app.services.audit_service import RequestContext
from app.services.auth_service import AuthService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a staff account (default role ADMIN)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=[r.value for r in Role], default=Role.ADMIN.value)
    parser.add_argument("--session", type=int, default=None, help="Assigned session id (SCANNER only)")
    parser.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")
    args = parser.parse_args(argv)

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match", file=sys.stderr)
            return 2
    try:
        validate_password_strength(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.role != Role.SCANNER.value and args.session is not None:
        print("--session is only valid for SCANNER accounts", file=sys.stderr)
        return 2

    with get_sessionmaker()() as db:
        try:
            user = AuthService(db).create_user(
                full_name=args.name,
                email=args.email,
                password=password,
                role=args.role,
                assigned_session_id=args.session,
                ctx=RequestContext(actor_role="SYSTEM", request_id="cli:create_admin"),
            )
        except AppError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
    print(f"Created {args.role} account {user.email} (id {user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
