from __future__ import annotations

import queue
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from ai_player import AIPlayer
from engine_info import Action, Player
from game_info import GameInfoState, GamePlayerAction, GameResult


@dataclass
class ActionRequest:
    hand_number: int
    stage: str
    current_bet: int
    min_raise: int
    chips: int
    bet_in_round: int
    call_amount: int
    can_check: bool
    can_call: bool
    can_raise: bool
    can_all_in: bool


def build_action_request(game_state: GameInfoState, player: Player) -> ActionRequest:
    call_amount = max(0, game_state.current_bet - player.bet_in_round)
    can_check = game_state.current_bet <= player.bet_in_round
    can_call = call_amount > 0 and player.chips > 0
    can_raise = player.chips > 0
    can_all_in = player.chips > 0
    return ActionRequest(
        hand_number=game_state.hand_num,
        stage=game_state.stage.value,
        current_bet=game_state.current_bet,
        min_raise=game_state.min_raise,
        chips=player.chips,
        bet_in_round=player.bet_in_round,
        call_amount=call_amount,
        can_check=can_check,
        can_call=can_call,
        can_raise=can_raise,
        can_all_in=can_all_in,
    )


class WebHumanPlayer(AIPlayer):
    def __init__(
        self,
        name: str,
        action_queue: "queue.Queue[GamePlayerAction]",
        on_action_request: Optional[Callable[[ActionRequest, GameInfoState], None]] = None,
    ):
        super().__init__(Player(name=name))
        self._action_queue = action_queue
        self._on_action_request = on_action_request
        self._last_request: Optional[ActionRequest] = None
        self._waiting_since: Optional[float] = None

    @property
    def last_request(self) -> Optional[ActionRequest]:
        return self._last_request

    def make_decision(self, game_state: GameInfoState) -> GamePlayerAction:
        req = build_action_request(game_state, self.player)
        self._last_request = req
        self._waiting_since = time.time()
        if self._on_action_request:
            self._on_action_request(req, game_state)
        action = self._action_queue.get()
        self._waiting_since = None
        return action

    def reflect_on_game(self, game_state: GameInfoState, game_result: GameResult):
        return


class RandomBotPlayer(AIPlayer):
    def __init__(self, name: str, seed: Optional[int] = None):
        super().__init__(Player(name=name))
        self._rng = random.Random(seed)
        self.model_name = "random_bot"

    def make_decision(self, game_state: GameInfoState) -> GamePlayerAction:
        req = build_action_request(game_state, self.player)
        choices = []
        choices.append(Action.FOLD)
        if req.can_check:
            choices.append(Action.CHECK)
        if req.can_call:
            choices.append(Action.CALL)
        if req.can_raise:
            choices.append(Action.RAISE)
        if req.can_all_in:
            choices.append(Action.ALL_IN)

        action = self._rng.choice(choices)
        if action == Action.CALL:
            return GamePlayerAction(action=Action.CALL, amount=req.call_amount, play_reason="", behavior="")
        if action == Action.RAISE:
            min_raise = max(req.min_raise, 1)
            max_raise = max(min_raise, self.player.chips)
            amount = min(max_raise, min_raise + self._rng.randint(0, max(0, max_raise - min_raise)))
            return GamePlayerAction(action=Action.RAISE, amount=amount, play_reason="", behavior="")
        if action == Action.ALL_IN:
            return GamePlayerAction(action=Action.ALL_IN, amount=self.player.chips, play_reason="", behavior="")
        if action == Action.CHECK:
            return GamePlayerAction(action=Action.CHECK, amount=0, play_reason="", behavior="")
        return GamePlayerAction(action=Action.FOLD, amount=0, play_reason="", behavior="")

    def reflect_on_game(self, game_state: GameInfoState, game_result: GameResult):
        return


def parse_user_action(payload: Dict[str, Any]) -> GamePlayerAction:
    raw_action = str(payload.get("action", "")).lower().strip()
    amount = int(payload.get("amount", 0) or 0)

    if raw_action in {"fold", "f"}:
        return GamePlayerAction(action=Action.FOLD, amount=0, play_reason="", behavior="")
    if raw_action in {"check", "x"}:
        return GamePlayerAction(action=Action.CHECK, amount=0, play_reason="", behavior="")
    if raw_action in {"call", "c"}:
        return GamePlayerAction(action=Action.CALL, amount=amount, play_reason="", behavior="")
    if raw_action in {"raise", "r"}:
        return GamePlayerAction(action=Action.RAISE, amount=amount, play_reason="", behavior="")
    if raw_action in {"all-in", "allin", "all"}:
        return GamePlayerAction(action=Action.ALL_IN, amount=amount, play_reason="", behavior="")

    raise ValueError("unknown action")

