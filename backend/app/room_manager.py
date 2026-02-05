from __future__ import annotations

import asyncio
import logging
import queue
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_info import Action
from game_info import GameInfoState, GamePlayerAction
from game_controller import GameController

from .protocol import PlayerConfig, PlayerKind, RoomStatus
from .web_players import RandomBotPlayer, WebHumanPlayer, parse_user_action

logger = logging.getLogger("poker_backend")


def now_ts() -> float:
    return time.time()


def serialize_table_snapshot(controller: GameController, hero_name: str, reveal_hero_hand: bool = False) -> Dict[str, Any]:
    table = controller.table
    players = []
    for p in table.players:
        hand = None
        if reveal_hero_hand and p.name == hero_name and p.hand:
            hand = [str(c) for c in p.hand]
        players.append(
            {
                "name": p.name,
                "chips": p.chips,
                "bet_in_round": p.bet_in_round,
                "folded": p.folded,
                "all_in": p.all_in,
                "is_active": p.is_active,
                "hand": hand,
            }
        )

    return {
        "hand_number": table.hand_number,
        "stage": table.stage.value,
        "pot": table.pot,
        "current_bet": table.current_bet,
        "community_cards": [str(c) for c in table.community_cards],
        "dealer_position": table.dealer_position,
        "players": players,
    }


class RoomBroadcast:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._sockets: set[Any] = set()
        self._hero_sockets: set[Any] = set()

    async def add(self, ws: Any, is_hero: bool = False) -> None:
        async with self._lock:
            self._sockets.add(ws)
            if is_hero:
                self._hero_sockets.add(ws)

    async def remove(self, ws: Any) -> None:
        async with self._lock:
            self._sockets.discard(ws)
            self._hero_sockets.discard(ws)

    async def broadcast_json(self, data: Dict[str, Any], only_hero: bool = False) -> None:
        async with self._lock:
            sockets = list(self._hero_sockets if only_hero else self._sockets)
        to_remove = []
        for ws in sockets:
            try:
                await ws.send_json(data)
            except Exception:
                to_remove.append(ws)
        if to_remove:
            async with self._lock:
                for ws in to_remove:
                    self._sockets.discard(ws)
                    self._hero_sockets.discard(ws)


@dataclass
class Room:
    room_id: str
    hero_name: str
    hero_token: str
    config: Dict[str, Any]
    status: RoomStatus = RoomStatus.created
    created_at: float = field(default_factory=now_ts)
    broadcast: RoomBroadcast = field(default_factory=RoomBroadcast)
    seq: int = 0
    last_error: Optional[str] = None

    controller: Optional[GameController] = None
    engine_thread: Optional[threading.Thread] = None
    hero_action_queue: "queue.Queue" = field(default_factory=queue.Queue)
    hero_player: Optional[WebHumanPlayer] = None
    hero_connected: threading.Event = field(default_factory=threading.Event)
    last_action_request: Optional[Dict[str, Any]] = None

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class RoomManager:
    def __init__(self, project_root: Path):
        self._root = project_root
        self._rooms: Dict[str, Room] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active_room_id: Optional[str] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def create_room(self, req: Dict[str, Any], players: List[PlayerConfig]) -> Room:
        room_id = str(uuid.uuid4())[:8]
        hero_name = req["hero_name"]
        hero_token = secrets.token_urlsafe(24)
        room = Room(
            room_id=room_id,
            hero_name=hero_name,
            hero_token=hero_token,
            config={
                "small_blind": req["small_blind"],
                "big_blind": req["big_blind"],
                "initial_chips": req["initial_chips"],
                "num_hands": req["num_hands"],
                "players": [p.model_dump(exclude={"api_key"}) for p in players],
            },
        )
        with self._lock:
            self._rooms[room_id] = room
        self._prepare_engine(room, players)
        logger.info("engine_prepared room_id=%s hero=%s", room_id, hero_name)
        return room

    def list_rooms(self) -> List[Room]:
        with self._lock:
            return list(self._rooms.values())

    def get_room(self, room_id: str) -> Optional[Room]:
        with self._lock:
            return self._rooms.get(room_id)

    def get_active_room(self) -> Optional[Room]:
        with self._lock:
            rid = self._active_room_id
        return self.get_room(rid) if rid else None

    def start_single_game(self, req: Dict[str, Any], players: List[PlayerConfig]) -> Room:
        with self._lock:
            rid = self._active_room_id
            active = self._rooms.get(rid) if rid else None
            if active and active.engine_thread and active.engine_thread.is_alive():
                raise ValueError("game already running")

        room = self.create_room(req, players)
        with self._lock:
            self._active_room_id = room.room_id
        room.hero_connected.set()
        self.start_room(room.room_id)
        return room

    def validate_token(self, room_id: str, token: str) -> bool:
        room = self.get_room(room_id)
        return bool(room and secrets.compare_digest(room.hero_token, token))

    def submit_hero_action(self, room_id: str, token: str, payload: Dict[str, Any]) -> None:
        room = self.get_room(room_id)
        if not room:
            raise ValueError("room not found")
        if not secrets.compare_digest(room.hero_token, token):
            raise ValueError("unauthorized")
        if not room.hero_player or not room.hero_player.last_request:
            raise ValueError("not waiting for action")

        action = parse_user_action(payload)
        self._validate_action(room, action)
        room.hero_action_queue.put(action)
        logger.info("hero_action_submitted room_id=%s action=%s amount=%s", room_id, action.action, action.amount)

    def start_room(self, room_id: str) -> None:
        room = self.get_room(room_id)
        if not room:
            raise ValueError("room not found")
        if room.status in {RoomStatus.finished, RoomStatus.error}:
            return
        t = room.engine_thread
        if not t:
            raise ValueError("engine not prepared")
        if t.is_alive():
            return
        logger.info("engine_thread_starting room_id=%s", room_id)
        t.start()

    def _validate_action(self, room: Room, action: GamePlayerAction) -> None:
        req = room.hero_player.last_request if room.hero_player else None
        if not req:
            raise ValueError("not waiting for action")

        if action.action == Action.CHECK and not req.can_check:
            raise ValueError("cannot check")
        if action.action == Action.CALL and not req.can_call:
            raise ValueError("cannot call")
        if action.action == Action.RAISE:
            if not req.can_raise:
                raise ValueError("cannot raise")
            if action.amount < req.min_raise:
                raise ValueError("raise below min_raise")
            if action.amount > req.chips:
                raise ValueError("raise above chips")
        if action.action == Action.ALL_IN and not req.can_all_in:
            raise ValueError("cannot all-in")

        if action.action == Action.CALL:
            action.amount = req.call_amount
        if action.action == Action.ALL_IN:
            action.amount = req.chips

    def _prepare_engine(self, room: Room, players: List[PlayerConfig]) -> None:
        if room.engine_thread and room.engine_thread.is_alive():
            return

        def run() -> None:
            try:
                logger.info("engine_thread_waiting_for_hero room_id=%s", room.room_id)
                room.hero_connected.wait()
                logger.info("engine_thread_hero_connected room_id=%s", room.room_id)
                if room.status == RoomStatus.created:
                    room.status = RoomStatus.running

                controller = GameController(
                    small_blind=room.config["small_blind"],
                    big_blind=room.config["big_blind"],
                    initial_chips=room.config["initial_chips"],
                    reveal_hole_cards=False,
                    human_player_name=room.hero_name,
                )
                controller.log_dir = str(self._root / "game_logs")
                controller.game_logger.log_dir = controller.log_dir
                Path(controller.log_dir).mkdir(parents=True, exist_ok=True)

                room.controller = controller
                logger.info("engine_controller_ready room_id=%s game_id=%s", room.room_id, controller.game_id)

                def emit(type_: str, payload: Dict[str, Any]) -> None:
                    if not self._loop:
                        return
                    msg = {
                        "type": type_,
                        "seq": room.next_seq(),
                        "ts": now_ts(),
                        "payload": payload,
                    }
                    asyncio.run_coroutine_threadsafe(room.broadcast.broadcast_json(msg), self._loop)

                def emit_snapshot() -> None:
                    if not self._loop:
                        return

                    async def _send() -> None:
                        public_msg = {
                            "type": "STATE_SNAPSHOT",
                            "seq": room.next_seq(),
                            "ts": now_ts(),
                            "payload": serialize_table_snapshot(controller, room.hero_name, reveal_hero_hand=False),
                        }
                        await room.broadcast.broadcast_json(public_msg)
                        hero_msg = {
                            "type": "STATE_SNAPSHOT",
                            "seq": room.next_seq(),
                            "ts": now_ts(),
                            "payload": serialize_table_snapshot(controller, room.hero_name, reveal_hero_hand=True),
                        }
                        await room.broadcast.broadcast_json(hero_msg, only_hero=True)

                    asyncio.run_coroutine_threadsafe(_send(), self._loop)

                def on_action_request(req_obj: Any, game_state: GameInfoState) -> None:
                    payload = {
                        "hero": room.hero_name,
                        "hand_number": req_obj.hand_number,
                        "stage": req_obj.stage,
                        "current_bet": req_obj.current_bet,
                        "min_raise": req_obj.min_raise,
                        "chips": req_obj.chips,
                        "bet_in_round": req_obj.bet_in_round,
                        "call_amount": req_obj.call_amount,
                        "legal_actions": {
                            "fold": True,
                            "check": req_obj.can_check,
                            "call": req_obj.can_call,
                            "raise": req_obj.can_raise,
                            "all_in": req_obj.can_all_in,
                        },
                    }
                    room.last_action_request = payload
                    emit("ACTION_REQUEST", payload)
                    emit_snapshot()

                hero = WebHumanPlayer(room.hero_name, room.hero_action_queue, on_action_request=on_action_request)
                room.hero_player = hero
                controller.add_player(hero)

                for idx, p in enumerate(players):
                    if p.name == room.hero_name:
                        continue
                    if p.kind == PlayerKind.random_bot:
                        controller.add_player(RandomBotPlayer(p.name, seed=idx + 1))
                    elif p.kind == PlayerKind.llm_openai:
                        from ai_player import OpenAiLLMUser

                        ai = OpenAiLLMUser(
                            name=p.name,
                            model_name=p.model_name or "qwen3-max",
                            api_key=p.api_key,
                            base_url=p.base_url,
                        )
                        ai.reveal_hand_in_stdout = True
                        ai.show_llm_stdout = True
                        controller.add_player(ai)
                    elif p.kind == PlayerKind.llm_anthropic:
                        from ai_player import AnthropicLLMUser

                        ai = AnthropicLLMUser(
                            name=p.name,
                            model_name=p.model_name or "claude-3-5-sonnet-20241022",
                            api_key=p.api_key,
                            base_url=p.base_url,
                        )
                        ai.reveal_hand_in_stdout = True
                        ai.show_llm_stdout = True
                        controller.add_player(ai)
                    else:
                        controller.add_player(RandomBotPlayer(p.name, seed=idx + 1))

                table = controller.table

                original_start_new_hand = table.start_new_hand
                original_move_to_next_stage = table.move_to_next_stage
                original_log_action = table.log_action
                original_award_pot = table.award_pot

                def start_new_hand_hook() -> None:
                    original_start_new_hand()
                    logger.info("hand_start room_id=%s hand=%s", room.room_id, table.hand_number)
                    logger.info(
                        "hole_cards room_id=%s hand=%s %s",
                        room.room_id,
                        table.hand_number,
                        " | ".join(f"{p.name}:{','.join(str(c) for c in (p.hand or []))}" for p in table.players),
                    )
                    emit(
                        "HAND_START",
                        {
                            "hand_number": table.hand_number,
                            "dealer_position": table.dealer_position,
                            "small_blind": table.small_blind,
                            "big_blind": table.big_blind,
                        },
                    )
                    emit_snapshot()

                def move_to_next_stage_hook() -> None:
                    prev_stage = table.stage.value
                    original_move_to_next_stage()
                    new_stage = table.stage.value
                    if new_stage != prev_stage:
                        logger.info("stage_change room_id=%s hand=%s %s->%s", room.room_id, table.hand_number, prev_stage, new_stage)
                    if new_stage != prev_stage and new_stage in {"flop", "turn", "river"}:
                        emit(
                            "STREET_DEALT",
                            {
                                "hand_number": table.hand_number,
                                "stage": new_stage,
                                "community_cards": [str(c) for c in table.community_cards],
                            },
                        )
                        emit_snapshot()
                    if new_stage == "showdown":
                        active = [p for p in table.players if p.is_active and not p.folded]
                        emit(
                            "SHOWDOWN_REVEAL",
                            {
                                "hand_number": table.hand_number,
                                "community_cards": [str(c) for c in table.community_cards],
                                "players": [
                                    {"name": p.name, "hand": [str(c) for c in p.hand], "chips": p.chips}
                                    for p in active
                                ],
                            },
                        )

                def log_action_hook(player: Any, action: Action, amount: int = 0, behavior: str = "") -> None:
                    original_log_action(player, action, amount, behavior)
                    logger.info(
                        "action_taken room_id=%s hand=%s stage=%s player=%s action=%s amount=%s",
                        room.room_id,
                        table.hand_number,
                        table.stage.value,
                        getattr(player, "name", "?"),
                        action.value,
                        amount,
                    )
                    emit(
                        "ACTION_TAKEN",
                        {
                            "hand_number": table.hand_number,
                            "stage": table.stage.value,
                            "player_name": player.name,
                            "action": action.value,
                            "amount": amount,
                            "pot": table.pot,
                            "player_chips": player.chips,
                            "behavior": behavior,
                        },
                    )
                    emit_snapshot()

                def award_pot_hook(winners: Any) -> None:
                    original_award_pot(winners)
                    record = table.game_log[-1] if table.game_log else None
                    if record and record.get("type") == 5:
                        emit("POT_AWARD", record)
                        emit_snapshot()

                table.start_new_hand = start_new_hand_hook
                table.move_to_next_stage = move_to_next_stage_hook
                table.log_action = log_action_hook
                table.award_pot = award_pot_hook
                emit_snapshot()

                controller.run_tournament(num_hands=room.config["num_hands"], verbose=False)
                enhanced_path = controller.save_enhanced_log()
                room.status = RoomStatus.finished
                logger.info("game_finished room_id=%s game_id=%s", room.room_id, controller.game_id)
                emit("GAME_END", {"game_id": controller.game_id, "enhanced_log": enhanced_path})
            except Exception as e:
                room.status = RoomStatus.error
                room.last_error = str(e)
                logger.exception("engine_error room_id=%s err=%s", room.room_id, room.last_error)
                if self._loop:
                    msg = {
                        "type": "ERROR",
                        "seq": room.next_seq(),
                        "ts": now_ts(),
                        "payload": {"error": room.last_error},
                    }
                    asyncio.run_coroutine_threadsafe(room.broadcast.broadcast_json(msg), self._loop)

        t = threading.Thread(target=run, daemon=True, name=f"room-{room.room_id}")
        room.engine_thread = t


def default_players(hero_name: str) -> List[PlayerConfig]:
    return [
        PlayerConfig(name=hero_name, kind=PlayerKind.human),
        PlayerConfig(name="BotA", kind=PlayerKind.random_bot),
        PlayerConfig(name="BotB", kind=PlayerKind.random_bot),
    ]
