"""Register a Telegram bot without putting its token in .env or shell history.

Usage inside the backend container:
    python scripts/register_telegram_channel.py --business-id 1 --bot-id 123 \
      --webhook-secret 'a-long-random-secret' --name 'Shop Telegram'
"""

import argparse
import getpass
import sys
from pathlib import Path

# When a script is executed as ``python scripts/foo.py``, Python puts the
# scripts directory on sys.path instead of the application root. Add /app so
# the container can import the ``app`` package without requiring PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.database.session import SessionLocal
from app.services.channel_service import upsert_channel_connection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", type=int, required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--webhook-secret", required=True)
    parser.add_argument("--name", default="Telegram Bot")
    args = parser.parse_args()
    if not settings.CHANNEL_ENCRYPTION_KEY:
        raise SystemExit("CHANNEL_ENCRYPTION_KEY is required")
    token = getpass.getpass("Telegram bot token (hidden): ")
    if not token:
        raise SystemExit("Telegram bot token is required")
    with SessionLocal() as db:
        channel = upsert_channel_connection(
            db,
            business_id=args.business_id,
            channel_type="telegram",
            external_account_id=args.bot_id,
            name=args.name,
            access_token=token,
            config={"webhook_secret": args.webhook_secret},
            encryption_key=settings.CHANNEL_ENCRYPTION_KEY,
        )
    print(f"Registered Telegram channel id={channel.id} business_id={channel.business_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
