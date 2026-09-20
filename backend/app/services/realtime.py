from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket


@dataclass(frozen=True)
class RealtimeConnection:
    """Identity bound to one authenticated CRM WebSocket."""

    business_id: int
    user_id: int


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[WebSocket, RealtimeConnection] = {}

    async def connect(
        self,
        websocket: WebSocket,
        *,
        business_id: int,
        user_id: int,
    ) -> None:
        await websocket.accept()
        self.active_connections[websocket] = RealtimeConnection(
            business_id=int(business_id),
            user_id=int(user_id),
        )

    def disconnect(
        self,
        websocket: WebSocket,
    ) -> None:
        self.active_connections.pop(websocket, None)

    def is_user_connected(self, *, business_id: int, user_id: int) -> bool:
        """Return whether a staff member currently has an active CRM session.

        The browser keeps this authenticated WebSocket open for as long as the
        employee is working in the CRM. It is therefore the right signal for
        whether an assigned conversation should notify that employee alone or
        fall back to the shared shop inbox when they leave.
        """
        return any(
            connection.business_id == int(business_id)
            and connection.user_id == int(user_id)
            for connection in self.active_connections.values()
        )

    async def broadcast(
        self,
        event: dict[str, Any],
        *,
        business_id: int,
        user_ids: set[int] | None = None,
    ) -> None:
        """Send an event only to authenticated sessions in one shop.

        ``user_ids`` is optional: omit it for a shop-wide event, or provide a
        set to target the staff member(s) responsible for the conversation.
        """
        payload = json.dumps(
            event,
            ensure_ascii=False,
            default=str,
        )

        stale: list[WebSocket] = []

        for websocket, connection in list(self.active_connections.items()):
            if connection.business_id != int(business_id):
                continue
            if user_ids is not None and connection.user_id not in user_ids:
                continue
            try:
                await websocket.send_text(
                    payload
                )
            except Exception:
                stale.append(
                    websocket
                )

        for websocket in stale:
            self.disconnect(
                websocket
            )


manager = ConnectionManager()


def schedule_broadcast(
    event: dict[str, Any],
    *,
    business_id: int,
    user_ids: set[int] | None = None,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    loop.create_task(
        manager.broadcast(
            event,
            business_id=business_id,
            user_ids=user_ids,
        )
    )
