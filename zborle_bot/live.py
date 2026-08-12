"""WebSocket fan-out so players see each other's progress inside the Activity.

Only tile colours and guess counts are broadcast, never letters or the answer. A player
watching someone else's board must not be able to reconstruct the word from it.

Authentication happens in the first message rather than a query parameter, because URLs
end up in proxy logs and browser history and the access token should not.
"""

import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)


class LiveHub:
    """Tracks open sockets per activity instance and broadcasts board updates."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def join(self, instance_id: str, socket: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(instance_id, set()).add(socket)

    async def leave(self, instance_id: str, socket: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(instance_id)
            if not room:
                return
            room.discard(socket)
            if not room:
                del self._rooms[instance_id]

    def occupancy(self, instance_id: str) -> int:
        return len(self._rooms.get(instance_id, ()))

    async def broadcast(self, instance_id: str, payload: dict) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(instance_id, ()))

        if not sockets:
            return

        dead: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_json(payload)
            except Exception:
                # A closed socket must not stop the rest of the room from updating.
                dead.append(socket)

        for socket in dead:
            await self.leave(instance_id, socket)


hub = LiveHub()
