from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from .protocol import (
    ClientWsEnvelope,
    PlayerConfig,
    PlayerKind,
    StartGameRequest,
    StartGameResponse,
)
from .room_manager import RoomManager, default_players, serialize_table_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)
logger = logging.getLogger("poker_backend")

app = FastAPI(title="Poker LLM Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

room_manager = RoomManager(project_root=PROJECT_ROOT)


@app.on_event("startup")
async def _on_startup() -> None:
    load_dotenv(override=True)
    room_manager.set_loop(asyncio.get_running_loop())
    logger.info("startup ok project_root=%s", PROJECT_ROOT)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/start", response_model=StartGameResponse)
async def start_game(req: StartGameRequest) -> StartGameResponse:
    initial_chips = req.initial_chips if req.initial_chips is not None else int(os.getenv("INITIAL_CHIPS", "1000"))
    small_blind = req.small_blind if req.small_blind is not None else int(os.getenv("SMALL_BLIND", "5"))
    big_blind = req.big_blind if req.big_blind is not None else int(os.getenv("BIG_BLIND", "10"))
    num_hands = req.num_hands if req.num_hands is not None else int(os.getenv("NUM_HANDS", "10"))

    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    anthropic_base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    if not openai_api_key and not anthropic_api_key:
        raise HTTPException(status_code=400, detail="请至少配置 OPENAI_API_KEY 或 ANTHROPIC_API_KEY")

    players = [PlayerConfig(name=req.human_name, kind=PlayerKind.human)]
    if openai_api_key:
        players.append(
            PlayerConfig(
                name="Qwen3-max",
                kind=PlayerKind.llm_openai,
                model_name="qwen3-max",
                api_key=openai_api_key,
                base_url=openai_base_url,
            )
        )
    if anthropic_api_key:
        players.append(
            PlayerConfig(
                name="Claude",
                kind=PlayerKind.llm_anthropic,
                model_name="claude-3-5-sonnet-20241022",
                api_key=anthropic_api_key,
                base_url=anthropic_base_url,
            )
        )

    try:
        room = room_manager.start_single_game(
            {
                "small_blind": small_blind,
                "big_blind": big_blind,
                "initial_chips": initial_chips,
                "num_hands": num_hands,
                "hero_name": req.human_name,
            },
            players,
        )
    except ValueError as e:
        if str(e) == "game already running":
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("single_game_started room_id=%s hero=%s", room.room_id, room.hero_name)
    return StartGameResponse(hero_token=room.hero_token, status=room.status, ws_url=f"/ws?token={room.hero_token}")


@app.post("/actions")
async def submit_action(token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = room_manager.get_active_room()
    if not r:
        raise HTTPException(status_code=404, detail="game not started")
    try:
        room_manager.submit_hero_action(r.room_id, token, payload)
    except ValueError as e:
        msg = str(e)
        if msg == "unauthorized":
            raise HTTPException(status_code=401, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@app.get("/snapshot")
async def get_snapshot(token: Optional[str] = None) -> Dict[str, Any]:
    r = room_manager.get_active_room()
    if not r:
        raise HTTPException(status_code=404, detail="game not started")
    if token is not None and not room_manager.validate_token(r.room_id, token):
        raise HTTPException(status_code=401, detail="unauthorized")
    reveal_hero_hand = token is not None and room_manager.validate_token(r.room_id, token)
    payload = serialize_table_snapshot(r.controller, r.hero_name, reveal_hero_hand=reveal_hero_hand) if r.controller else {}
    return {"type": "STATE_SNAPSHOT", "seq": r.next_seq(), "ts": time.time(), "payload": payload, "status": r.status}


@app.websocket("/ws")
async def ws_game(websocket: WebSocket, token: Optional[str] = None) -> None:
    r = room_manager.get_active_room()
    if not r:
        await websocket.close(code=1008)
        return

    hero_authed = token is not None and room_manager.validate_token(r.room_id, token)
    await websocket.accept()
    await r.broadcast.add(websocket, is_hero=hero_authed)
    logger.info("ws_connected single room_id=%s hero_authed=%s", r.room_id, hero_authed)

    try:
        if r.controller:
            await websocket.send_json(
                {
                    "type": "STARTED",
                    "seq": r.next_seq(),
                    "ts": time.time(),
                    "payload": {"hero": hero_authed},
                }
            )
            await websocket.send_json(
                {
                    "type": "STATE_SNAPSHOT",
                    "seq": r.next_seq(),
                    "ts": time.time(),
                    "payload": serialize_table_snapshot(r.controller, r.hero_name, reveal_hero_hand=hero_authed),
                }
            )
            if hero_authed and r.last_action_request:
                await websocket.send_json(
                    {
                        "type": "ACTION_REQUEST",
                        "seq": r.next_seq(),
                        "ts": time.time(),
                        "payload": r.last_action_request,
                    }
                )
        while True:
            raw = await websocket.receive_json()
            try:
                msg = ClientWsEnvelope.model_validate(raw)
            except Exception:
                await websocket.send_json({"type": "ERROR", "payload": {"error": "invalid message"}})
                continue

            if msg.type == "PING":
                await websocket.send_json({"type": "PONG", "seq": r.next_seq(), "ts": time.time(), "payload": {}})
                continue

            if msg.type == "REQUEST_SNAPSHOT":
                if r.controller:
                    await websocket.send_json(
                        {
                            "type": "STATE_SNAPSHOT",
                            "seq": r.next_seq(),
                            "ts": time.time(),
                            "payload": serialize_table_snapshot(r.controller, r.hero_name, reveal_hero_hand=hero_authed),
                        }
                    )
                    if hero_authed and r.last_action_request:
                        await websocket.send_json(
                            {
                                "type": "ACTION_REQUEST",
                                "seq": r.next_seq(),
                                "ts": time.time(),
                                "payload": r.last_action_request,
                            }
                        )
                continue

            if msg.type == "USER_ACTION":
                if not hero_authed or not token:
                    await websocket.send_json({"type": "ERROR", "payload": {"error": "unauthorized"}})
                    continue
                try:
                    room_manager.submit_hero_action(r.room_id, token, msg.payload)
                    await websocket.send_json({"type": "ACK", "seq": r.next_seq(), "ts": time.time(), "payload": {}})
                except ValueError as e:
                    await websocket.send_json(
                        {"type": "ERROR", "seq": r.next_seq(), "ts": time.time(), "payload": {"error": str(e)}}
                    )
                continue
    except WebSocketDisconnect:
        return
    finally:
        await r.broadcast.remove(websocket)
