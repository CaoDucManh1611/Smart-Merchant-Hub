"""Read-only validation of locally saved connector pairings before startup."""
import json
import sys
from fastapi import HTTPException
from app.api.local_connectors import _connector_channel, _tenant_schema
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.channel import Channel


def main():
    entries = json.loads(sys.stdin.read().lstrip("\ufeff"))
    results = []
    with PlatformSessionLocal() as platform:
        for entry in entries:
            kind = entry["kind"]
            try:
                business, channel_id = _connector_channel(kind, "Bearer " + entry["token"], platform)
                with tenant_session(_tenant_schema(platform, business)) as db:
                    channel = db.get(Channel, channel_id)
                    config = channel.config if isinstance(channel.config, dict) else {}
                    allowed = (config.get("provider") == kind + "_local_connector"
                               and config.get("connector_execution_mode", "local") != "server")
                results.append({"kind": kind, "allowed": allowed, "reason": "active_local" if allowed else "not_local_connector"})
            except HTTPException as error:
                if error.status_code not in (400, 401, 403, 404, 503):
                    raise
                results.append({"kind": kind, "allowed": False, "reason": "credentials_unavailable" if error.status_code == 503 else "disconnected_or_old_pairing"})
    print(json.dumps(results))

if __name__ == "__main__":
    main()
