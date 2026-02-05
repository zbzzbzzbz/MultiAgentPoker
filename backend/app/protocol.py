from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class RoomStatus(str, Enum):
    created = "created"
    running = "running"
    finished = "finished"
    error = "error"


class PlayerKind(str, Enum):
    human = "human"
    random_bot = "random_bot"
    llm_openai = "llm_openai"
    llm_anthropic = "llm_anthropic"


class PlayerConfig(BaseModel):
    name: str
    kind: PlayerKind = PlayerKind.random_bot
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


ViewMode = Literal["debug", "user"]


class StartGameRequest(BaseModel):
    view: ViewMode = "debug"
    human_name: str = "You"
    initial_chips: Optional[int] = None
    small_blind: Optional[int] = None
    big_blind: Optional[int] = None
    num_hands: Optional[int] = None


class StartGameResponse(BaseModel):
    hero_token: str
    status: RoomStatus
    ws_url: str


WsType = Literal[
    "STATE_SNAPSHOT",
    "HAND_START",
    "STREET_DEALT",
    "ACTION_REQUEST",
    "ACTION_TAKEN",
    "SHOWDOWN_REVEAL",
    "POT_AWARD",
    "HAND_RESULT",
    "GAME_END",
    "STARTED",
    "ACK",
    "PONG",
    "ERROR",
]


class WsEnvelope(BaseModel):
    type: WsType
    seq: int
    ts: float
    payload: Dict[str, Any] = Field(default_factory=dict)


ClientWsType = Literal["USER_ACTION", "REQUEST_SNAPSHOT", "PING"]


class ClientWsEnvelope(BaseModel):
    type: ClientWsType
    payload: Dict[str, Any] = Field(default_factory=dict)
