from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(
        self,
        websocket: WebSocket,
    ) -> None:
        await websocket.accept()
        self.active_connections.append(
            websocket
        )

    def disconnect(
        self,
        websocket: WebSocket,
    ) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(
                websocket
            )

    async def broadcast(
        self,
        event: dict[str, Any],
    ) -> None:
        payload = json.dumps(
            event,
            ensure_ascii=False,
            default=str,
        )

        stale: list[WebSocket] = []

        for websocket in list(
            self.active_connections
        ):
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
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    loop.create_task(
        manager.broadcast(
            event
        )
    )
