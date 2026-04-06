from fastapi import WebSocket
from typing import Dict, List


from src.utils.logger import logger


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, set] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]

    async def subscribe(self, websocket: WebSocket, channels: List[str]):
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(channels)

    async def broadcast(self, channel: str, message: dict):
        for connection in list(self.active_connections):
            if channel in self.subscriptions.get(connection, set()):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(connection)


manager = ConnectionManager()
