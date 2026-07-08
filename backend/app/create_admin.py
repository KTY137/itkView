"""Create or update an admin user (docs/06).

The password is read from --password or the ITKFLOW_ADMIN_PASSWORD environment
variable — never hardcoded and never stored in the repo.

    python -m app.create_admin --email admin@tudo.example --name "Admin" \
        --institute TUDO --password "<chosen>"
"""

import argparse
import os
import sys

from sqlalchemy import select

from app.auth import hash_password
from app.config import get_settings
from app.db import Base, ensure_phase0_sqlite_schema, make_engine, make_session_factory
from app.models import InstituteProfile, User


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create or update an itkFlow admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None, help="display name (defaults to the email)")
    parser.add_argument("--institute", default=None, help="institute code to attach the admin to")
    parser.add_argument("--password", default=None, help="or set ITKFLOW_ADMIN_PASSWORD")
    args = parser.parse_args(argv)

    password = args.password or os.environ.get("ITKFLOW_ADMIN_PASSWORD")
    if not password:
        sys.exit("No password given. Use --password or set ITKFLOW_ADMIN_PASSWORD.")

    settings = get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    ensure_phase0_sqlite_schema(engine)

    with make_session_factory(engine)() as session:
        institute = None
        if args.institute:
            institute = session.scalar(
                select(InstituteProfile).where(InstituteProfile.code == args.institute)
            )
            if institute is None:
                sys.exit(f"Institute '{args.institute}' not found. Seed or create it first.")

        email = args.email.strip().lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name=args.name or email,
                role="admin",
                institute_id=institute.id if institute else None,
                password_hash=hash_password(password),
                is_active=True,
            )
            session.add(user)
            action = "created"
        else:
            user.role = "admin"
            user.is_active = True
            user.password_hash = hash_password(password)
            if institute is not None:
                user.institute_id = institute.id
            if args.name:
                user.display_name = args.name
            action = "updated"
        session.commit()
        print(f"Admin {action}: {email}")


if __name__ == "__main__":
    main()
