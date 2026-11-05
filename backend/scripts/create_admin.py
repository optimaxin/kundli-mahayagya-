"""Create the first ADMIN (or any staff) account securely, from a developer machine.

Safety rules
* The password is never a command-line argument (shell history / process lists). It is read
  from a hidden prompt (asked twice), or from stdin with --password-stdin for automation.
* The target database comes from the backend's normal configuration (DATABASE_URL in the
  environment or backend/.env), exactly like the deployed API. It is shown with the
  password hidden.
* With APP_ENV=production you must type PRODUCTION to continue (or pass --yes-production,
  which is required together with --password-stdin).
* An existing account is never changed: if the email is already registered the command
  stops, reports the existing role/status, and exits with code 3. Use the admin console
  (Volunteers -> reset password) or change-password to change a password.
* No default or hard-coded credentials; the creation is written to the audit log.

Usage (run from the backend/ folder):
    python -m scripts.create_admin --email admin@example.org --name "Event Admin"
    python -m scripts.create_admin --email gate1@example.org --name "Gate 1" --role SCANNER --session 1

Exit codes: 0 created, 1 error, 2 invalid input / not confirmed, 3 account already exists.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.errors import AppError
from app.core.security import validate_password_strength
from app.models.enums import Role
from app.services.audit_service import RequestContext
from app.services.auth_service import AuthService

EXIT_OK, EXIT_ERROR, EXIT_INPUT, EXIT_EXISTS = 0, 1, 2, 3


def _target_description() -> str:
    """host:port/database with the password removed."""
    url = make_url(get_settings().DATABASE_URL)
    return f"{url.host}:{url.port or 5432}/{url.database}"


def _read_password(from_stdin: bool) -> str | None:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("Password (hidden): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match. Nothing was changed.", file=sys.stderr)
        return None
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a staff account (default role ADMIN)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=[r.value for r in Role], default=Role.ADMIN.value)
    parser.add_argument("--session", type=int, default=None, help="Assigned session id 1-16 (SCANNER only)")
    parser.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")
    parser.add_argument("--yes-production", action="store_true",
                        help="Confirm operating on the production database without the interactive prompt")
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.role != Role.SCANNER.value and args.session is not None:
        print("--session is only valid for SCANNER accounts", file=sys.stderr)
        return EXIT_INPUT
    try:
        args.email = TypeAdapter(EmailStr).validate_python(args.email.strip()).lower()
    except ValidationError:
        print("Invalid email address", file=sys.stderr)
        return EXIT_INPUT

    print(f"Target database : {_target_description()}  (APP_ENV={settings.APP_ENV})")
    if settings.is_production and not args.yes_production:
        if args.password_stdin:
            print("Refusing: APP_ENV=production. Add --yes-production to confirm when using --password-stdin.",
                  file=sys.stderr)
            return EXIT_INPUT
        answer = input("This is the PRODUCTION database. Type PRODUCTION to continue: ").strip()
        if answer != "PRODUCTION":
            print("Not confirmed. Nothing was changed.", file=sys.stderr)
            return EXIT_INPUT

    with get_sessionmaker()() as db:
        service = AuthService(db)
        try:
            existing = service.find_by_email(args.email.strip())
        except Exception as exc:  # connection problems: never print the URL/password
            print(f"Could not connect to the database ({type(exc).__name__}). Nothing was changed.", file=sys.stderr)
            return EXIT_ERROR
        if existing is not None:
            print(
                f"An account with this email already exists (role {existing.role}, "
                f"{'active' if existing.is_active else 'deactivated'}). Nothing was changed.\n"
                "To change its password, use the admin console or the change-password endpoint.",
                file=sys.stderr,
            )
            return EXIT_EXISTS
        db.rollback()

        password = _read_password(args.password_stdin)
        if password is None:
            return EXIT_INPUT
        try:
            validate_password_strength(password)
        except ValueError as exc:
            print(f"{exc}. Nothing was changed.", file=sys.stderr)
            return EXIT_INPUT

        try:
            user = service.create_user(
                full_name=args.name,
                email=args.email.strip(),
                password=password,
                role=args.role,
                assigned_session_id=args.session,
                ctx=RequestContext(actor_role="SYSTEM", request_id="cli:create_admin"),
            )
        except AppError as exc:
            # EMAIL_EXISTS here means someone created the same account concurrently.
            print(f"Error: {exc.message}. Nothing was changed.", file=sys.stderr)
            return EXIT_EXISTS if exc.code == "EMAIL_EXISTS" else EXIT_ERROR
        print(f"Created {user.role} account {user.email} (id {user.id}). The creation is recorded in the audit log.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
