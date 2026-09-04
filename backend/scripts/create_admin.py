"""Create the first real CRM owner account.

Usage inside the backend container::

    python scripts/create_admin.py --business-id 1 \
      --email owner@example.com --name "Shop Owner"

The password is requested without echoing and is never written to the
environment, command history, or an audit payload.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# ``python scripts/foo.py`` sets sys.path to ``scripts/`` inside the image.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.database.bootstrap import ensure_default_business
from app.database.session import SessionLocal
from app.models.business import Business, User


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a CRM owner account")
    parser.add_argument("--business-id", type=int, default=None)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    password = getpass.getpass("Owner password (hidden, min 8 chars): ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")

    with SessionLocal() as db:
        business = (
            db.get(Business, args.business_id)
            if args.business_id is not None
            else ensure_default_business(db)
        )
        if business is None:
            raise SystemExit("Business not found.")

        email = args.email.strip().lower()
        existing = db.scalar(
            select(User).where(
                User.business_id == business.id,
                User.email == email,
            )
        )
        if existing is not None:
            raise SystemExit("A user with this email already exists.")

        user = User(
            business_id=business.id,
            full_name=args.name.strip(),
            email=email,
            password_hash=hash_password(password),
            role="owner",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        business_id = business.id
        user_id = user.id
        user_email = user.email

    print(f"Created owner user id={user_id} business_id={business_id} email={user_email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
