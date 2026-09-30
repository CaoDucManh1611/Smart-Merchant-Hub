"""Register a Zalo Official Account OpenAPI connection.

Usage inside the backend container:
    python scripts/register_zalo_oa_channel.py --business-id 1 \
      --oa-id 123456 --app-id 987654 \
      --name 'Shop Zalo OA'

The OA access token is requested interactively so it is not written to shell
history.  The webhook secret is encrypted before it is persisted in channel
configuration.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.database.session import SessionLocal
from app.services.channel_credentials import encrypt_token
from app.services.channel_service import upsert_channel_connection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", type=int, required=True)
    parser.add_argument("--oa-id", required=True)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--oa-secret-key")
    parser.add_argument("--name", default="Zalo OA")
    args = parser.parse_args()

    if not settings.CHANNEL_ENCRYPTION_KEY:
        raise SystemExit("CHANNEL_ENCRYPTION_KEY is required")
    access_token = getpass.getpass("Zalo OA access token (hidden): ")
    if not access_token:
        raise SystemExit("Zalo OA access token is required")
    oa_secret_key = args.oa_secret_key or getpass.getpass("Zalo OA webhook secret key (hidden): ")
    if not oa_secret_key:
        raise SystemExit("Zalo OA webhook secret key is required")

    config = {
        "provider": "zalo_oa",
        "oa_app_id": str(args.app_id),
        "oa_id": str(args.oa_id),
        "oa_secret_key_encrypted": encrypt_token(
            oa_secret_key,
            settings.CHANNEL_ENCRYPTION_KEY,
        ),
    }
    with SessionLocal() as db:
        channel = upsert_channel_connection(
            db,
            business_id=args.business_id,
            channel_type="zalo",
            external_account_id=str(args.oa_id),
            name=args.name,
            access_token=access_token,
            config=config,
            encryption_key=settings.CHANNEL_ENCRYPTION_KEY,
        )
    print(f"Registered Zalo OA channel id={channel.id} business_id={channel.business_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
