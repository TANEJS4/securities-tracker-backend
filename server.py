import asyncio
import json
from collections import defaultdict
from contextlib import asynccontextmanager

import yaml
from yaml.representer import Representer, SafeRepresenter
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


from src.service.websocket_data import data_service, hooked_handle_message
from src.integration.wealthsimple_integration import (
    WealthSimpleManager,
    get_wealthsimple_portfolio,
)
from src.websocket.socket import manager

import config
from src.utils.logger import logger
from src.route.api import router
from src.route.api import router

yaml.add_representer(defaultdict, Representer.represent_dict)
yaml.representer.SafeRepresenter.add_representer(
    defaultdict, SafeRepresenter.represent_dict
)


load_dotenv()

setattr(config, "previous_closes", {})

data_service.handle_message = hooked_handle_message


@asynccontextmanager
async def lifespan(app: FastAPI):
    ws_manager = WealthSimpleManager()
    wealthsimple_portfolio = get_wealthsimple_portfolio(manager=ws_manager)

    with open("SYMBOLS.yaml", "w") as file:
        yaml.dump(
            wealthsimple_portfolio,
            file,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    asyncio.create_task(data_service.start_stream())
    yield
    # Shut down (nothing specific to await)


app = FastAPI(lifespan=lifespan)


app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "subscribe":
                    channels = msg.get("channels", [])
                    await manager.subscribe(websocket, channels)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
