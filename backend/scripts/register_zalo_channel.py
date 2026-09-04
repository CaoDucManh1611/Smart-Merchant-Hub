"""Register a Zalo Bot Creator connection without storing its token in .env.

Usage inside the backend container:
    python scripts/register_zalo_channel.py --business-id 1 --bot-id 8827133344 \
      --webhook-secret 'the-same-secret-used-in-setWebhook' --name 'Shop Zalo Bot'
"""

import argparse
import getpass
import sys
from pathlib import Path

# ``python scripts/foo.py`` sets sys.path[0] to ``scripts``.  Add the
# application root so the script works both locally and in the /app container.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.database.session import SessionLocal
from app.services.channel_service import upsert_channel_connection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", type=int, required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--webhook-secret", required=True)
    parser.add_argument("--name", default="Zalo Bot")
    args = parser.parse_args()

    if not settings.CHANNEL_ENCRYPTION_KEY:
        raise SystemExit("CHANNEL_ENCRYPTION_KEY is required")

    token = getpass.getpass("Zalo Bot token (hidden): ")
    if not token:
        raise SystemExit("Zalo Bot token is required")

    with SessionLocal() as db:
        channel = upsert_channel_connection(
            db,
            business_id=args.business_id,
            channel_type="zalo",
            external_account_id=args.bot_id,
            name=args.name,
            access_token=token,
            config={"webhook_secret": args.webhook_secret},
            encryption_key=settings.CHANNEL_ENCRYPTION_KEY,
        )

    print(f"Registered Zalo channel id={channel.id} business_id={channel.business_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
