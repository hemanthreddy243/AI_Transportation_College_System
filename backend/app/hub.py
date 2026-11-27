"""In-process WebSocket hub: pushes live bus updates to whoever is watching.

Students subscribe to their own bus, admins to the whole fleet. Runs inside a single
server process; for several server processes, swap this for Redis pub/sub.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class Hub:
    def __init__(self):
        self.by_bus: dict[int, set[WebSocket]] = defaultdict(set)
        self.fleet: set[WebSocket] = set()

    def join(self, ws: WebSocket, bus_id: int | None):
        (self.fleet if bus_id is None else self.by_bus[bus_id]).add(ws)

    def leave(self, ws: WebSocket, bus_id: int | None):
        (self.fleet if bus_id is None else self.by_bus[bus_id]).discard(ws)

    async def publish(self, bus_id: int, payload: dict):
        targets = list(self.by_bus.get(bus_id, ())) + list(self.fleet)
        if not targets:
            return
        message = {"type": "bus", "data": payload}
        results = await asyncio.gather(*(ws.send_json(message) for ws in targets), return_exceptions=True)
        for ws, res in zip(targets, results):
            if isinstance(res, Exception):  # closed socket
                self.leave(ws, None)
                self.leave(ws, bus_id)


hub = Hub()
