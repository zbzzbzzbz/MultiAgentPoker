# ai_player.py
# AI玩家接口和实现

import random
import time
from typing import List, Dict, Any, Tuple, Optional
from engine_info import Card, Action, GameStage, Player
from openai import OpenAI
from game_info import GameAction, GameInfoState, GamePlayerAction, GameResult
import re
from anthropic import Anthropic

DESISION_PROMPT_PATH = "prompt/decision_prompt.txt"
REFLECT_PROMPT_PATH = "prompt/reflect_prompt.txt"
REFLECT_ALL_PROMPT_PATH = "prompt/reflect_all_prompt.txt"
RED = '\033[31m'
RESET = '\033[0m'


def prepare_game_state_for_log(game_state) -> Dict[str, Any]:
    """准备用于日志记录的游戏状态（避免循环引用）"""
    return {
        "hand": [str(card) for card in game_state.hand],
        "community_cards": [str(card) for card in game_state.community_cards],
        "pot": game_state.pot,
        "current_bet": game_state.current_bet,
        "min_raise": game_state.min_raise,
        "stage": game_state.stage.value,
        "position": game_state.position,
        "dealer_position": game_state.dealer_position,
        "small_blind": game_state.small_blind,
        "big_blind": game_state.big_blind,
        "hand_num": game_state.hand_num,
        "players_info": [
            {
                "name": p.name,
                "chips": p.chips,
                "bet_in_round": p.bet_in_round,
                "folded": p.folded,
                "all_in": p.all_in,
                "is_active": p.is_active
            }
            for p in game_state.players_info
        ]
    }


class AIPlayer:
    """AI玩家基类,定义AI玩家接口"""

    def __init__(self, player: Player):
        self.player = player
        self.name = player.name
        self.reveal_hand_in_stdout = True
        self.show_llm_stdout = True

    def make_decision(self, game_state: GameInfoState) -> GamePlayerAction:
        """根据游戏状态做出决策
        
        Args:
            game_state: 游戏状态信息，包括：
                - hand: 手牌
                - community_cards: 公共牌
                - pot: 底池
                - current_bet: 当前最高下注
                - min_raise: 最小加注额
                - stage: 当前游戏阶段
                - players_info: 其他玩家信息
                - position: 自己的位置
                - dealer_position: 庄家位置
                - action_history: 行动历史
        Returns:
        GamePlayerAction: 玩家行动，包含以下属性：
            - action: 行动类型，如FOLD、CHECK、CALL等
            - amount: 下注金额
            - play_reason: 行动理由
            - behavior: 行为描述
        """
        raise NotImplementedError("子类必须实现此方法")

    def reflect_on_game(self, game_state: GameInfoState, game_result: GameResult):
        """在游戏结束后，根据游戏结果进行反思和学习"""
        raise NotImplementedError("子类必须实现此方法")


class HumanPlayer(AIPlayer):
    def __init__(self, name: str):
        super().__init__(Player(name=name))

    def make_decision(self, game_state: GameInfoState) -> GamePlayerAction:
        print(f"\n轮到你行动：{self.name} ({game_state.stage.value})")
        print(f"公共牌：{', '.join(str(card) for card in game_state.community_cards) if game_state.community_cards else '暂无'}")
        print(f"底池：{game_state.pot}  当前最高下注：{game_state.current_bet}  你本轮已下注：{self.player.bet_in_round}")
        print(f"你的手牌：{', '.join(str(card) for card in self.player.hand)}")
        print(f"最小加注额：{game_state.min_raise}  你的剩余筹码：{self.player.chips}")

        print("玩家信息：")
        for i, p in enumerate(game_state.players_info):
            dealer_str = " (庄家)" if i == game_state.dealer_position else ""
            self_str = " (你)" if p.name == self.player.name else ""
            status = []
            if not p.is_active:
                status.append("出局")
            if p.folded:
                status.append("弃牌")
            if p.all_in:
                status.append("全押")
            status_str = f" [{' / '.join(status)}]" if status else ""
            print(f"- {p.name}{dealer_str}{self_str}: 位置{i}, 筹码{p.chips}, 本轮下注{p.bet_in_round}{status_str}")

        if game_state.action_history:
            print("最近行动：")
            recent = game_state.action_history[-8:]
            for a in recent:
                amount_str = f" {a.amount}" if a.amount else ""
                behavior_str = f" | {a.behavior}" if a.behavior else ""
                print(f"- {a.stage.value} {a.player_name} {a.action.value}{amount_str}{behavior_str}")

        can_check = game_state.current_bet <= self.player.bet_in_round
        call_amount = max(0, game_state.current_bet - self.player.bet_in_round)
        can_call = call_amount > 0 and self.player.chips > 0
        can_raise = self.player.chips > 0

        available = ["fold", "allin"]
        if can_check:
            available.append("check")
        if can_call:
            available.append("call")
        if can_raise:
            available.append("raise <金额>")
        print(f"可选行动：{', '.join(available)}")

        while True:
            raw = input("请输入行动：").strip()
            if not raw:
                continue
            parts = raw.split()
            cmd = parts[0].lower()

            if cmd in {"fold", "f"}:
                return GamePlayerAction(action=Action.FOLD, amount=0, play_reason="", behavior="")

            if cmd in {"check", "c"}:
                if not can_check:
                    print("当前不能过牌（有人下注且你未跟齐）。")
                    continue
                return GamePlayerAction(action=Action.CHECK, amount=0, play_reason="", behavior="")

            if cmd in {"call"}:
                if not can_call:
                    print("当前不能跟注。")
                    continue
                return GamePlayerAction(action=Action.CALL, amount=call_amount, play_reason="", behavior="")

            if cmd in {"allin", "all-in", "all"}:
                if self.player.chips <= 0:
                    print("你没有筹码可以全押。")
                    continue
                return GamePlayerAction(action=Action.ALL_IN, amount=self.player.chips, play_reason="", behavior="")

            if cmd in {"raise", "r"}:
                if len(parts) < 2:
                    print("请输入加注金额，例如：raise 50")
                    continue
                try:
                    amount = int(parts[1])
                except ValueError:
                    print("加注金额必须是整数。")
                    continue

                if amount < game_state.min_raise:
                    print(f"加注金额不能小于最小加注额：{game_state.min_raise}")
                    continue
                if amount > self.player.chips:
                    print("加注金额不能超过你的剩余筹码。")
                    continue
                return GamePlayerAction(action=Action.RAISE, amount=amount, play_reason="", behavior="")

            print("无法识别的行动。可用：fold / check / call / raise <金额> / allin")

    def reflect_on_game(self, game_state: GameInfoState, game_result: GameResult):
        return


class LLMPlayer(AIPlayer):
    """由大语言模型驱动的AI玩家"""

    def __init__(self, name: str, model_name: str, api_key: Optional[str] = None, base_url: Optional[str] = None, game_logger: Optional[Any] = None):
        super().__init__(Player(name=name))
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.client = None
        self.opinions = {}
        self.all_player_previous = '对他们还不了解'
        self.game_logger = game_logger  # 新增：日志记录器

    def _call_llm_api(self, prompt: str) -> str:
        """调用大语言模型API获取响应"""
        raise NotImplementedError("子类必须实现此方法")

    def _call_llm_api_with_metadata(self, prompt: str) -> Dict[str, str]:
        """调用大语言模型API获取响应及元数据"""
        # 默认实现，只返回内容
        content = self._call_llm_api(prompt)
        return {"content": content, "reasoning_content": ""}

    def make_decision(self, game_state: GameInfoState) -> GamePlayerAction:
        print(f"玩家 {self.name} 正在思考...", flush=True)
        if getattr(self, "reveal_hand_in_stdout", True):
            print(f"他的手牌是：{', '.join(str(card) for card in self.player.hand)}", flush=True)
            print(f"他的筹码量：{self.player.chips}", flush=True)

        prompt = ""
        raw_response = ""
        reasoning_content = ""
        error = ""
        start_time = time.time()
        game_state_dict = prepare_game_state_for_log(game_state)

        for i in range(3):
            try:
                # 构建提示信息
                prompt = self._build_prompt(game_state)

                # 调用大语言模型获取决策
                response_with_metadata = self._call_llm_api_with_metadata(prompt)
                raw_response = response_with_metadata.get("content", "")
                reasoning_content = response_with_metadata.get("reasoning_content", "")

                result = self._parse_response(raw_response, game_state)

                # 记录决策过程到日志
                if self.game_logger:
                    self.game_logger.log_llm_decision(
                        player_name=self.name,
                        model_name=self.model_name,
                        hand_number=game_state.hand_num,
                        stage=game_state.stage,
                        prompt=prompt,
                        game_state=game_state_dict,
                        raw_response=raw_response,
                        parsed_action=result.action,
                        action_amount=result.amount,
                        play_reason=result.play_reason,
                        behavior=result.behavior,
                        reasoning_content=reasoning_content,
                        response_time=time.time() - start_time,
                        error=error
                    )

                return result
            except Exception as e:
                error = str(e)
                print(e)

        # 如果所有重试都失败，记录失败的决策
        if self.game_logger:
            self.game_logger.log_llm_decision(
                player_name=self.name,
                model_name=self.model_name,
                hand_number=game_state.hand_num,
                stage=game_state.stage,
                prompt=prompt if prompt else "",
                game_state=game_state_dict,
                raw_response=raw_response if raw_response else "",
                parsed_action=Action.FOLD,
                action_amount=0,
                play_reason='大模型操作错误，直接弃牌',
                behavior='无表情',
                reasoning_content=reasoning_content,
                response_time=time.time() - start_time,
                error=error
            )

        return GamePlayerAction(
            action=Action.FOLD,
            amount=0,
            play_reason='大模型操作错误，直接弃牌',
            behavior='无表情'
        )

    def _build_prompt(self, game_state: GameInfoState) -> str:
        """构建提示信息"""
        basePrompt = self._read_file(DESISION_PROMPT_PATH)

        # 生成游戏游戏相关信息
        game_info = game_state.get_common_game_info()

        # 生成玩家当前信息
        self_info = self.get_self_current_round_info(game_state)

        # 生成所有玩家信息
        player_info = self.get_all_player_info(game_state)

        # 生成当前轮次的对局历史
        action_history = self.get_action_history(game_state.action_history)

        # 生成当前玩家对其他人物的评估
        player_performance = self.get_player_performance(game_state.players_info)

        prompt = basePrompt.format(
            game_info=game_info,
            self_info=self_info,
            player_info=player_info,
            action_history=action_history,
            player_performance=self.all_player_previous
        )

        return prompt

    def _parse_response(self, response: str, game_state: GameInfoState) -> GamePlayerAction:
        """解析大语言模型的响应"""
        import json

        # 提取JSON部分（防止模型输出额外文本）
        response = response.strip()

        json_match = re.search(r'({[\s\S]*})', response)

        if json_match:
            json_str = json_match.group(1)
            data = json.loads(json_str)

            # 提取action和amount
            action_str = data.get('action', '').strip().upper()
            amount = data.get('amount', 0)

            # 存储决策理由和行为描述
            play_reason = data.get('play_reason', '')
            behavior = data.get('behavior', '')
            action = Action.FOLD
            # 解析行动
            if action_str == 'FOLD':
                action = Action.FOLD
                amount = 0
            elif action_str == 'CHECK':
                action = Action.CHECK
                amount = 0
            elif action_str == 'CALL':
                action = Action.CALL
                amount = game_state.current_bet - self.player.bet_in_round
            elif action_str == 'ALL_IN':
                action = Action.ALL_IN
                amount = self.player.chips
            elif action_str == 'RAISE':
                # 确保加注金额合法
                min_raise = max(game_state.min_raise, game_state.current_bet * 2)
                amount = max(min_raise, amount)  # 确保金额不小于最小加注
                amount = min(amount, self.player.chips)  # 确保金额不超过玩家筹码
                action = Action.RAISE

            return GamePlayerAction(
                action=action,
                amount=amount,
                play_reason=play_reason,
                behavior=behavior
            )
        else:
            raise ValueError("无法从响应中提取有效数据")

    def reflect_on_game(self, game_state: GameInfoState, game_result: GameResult):
        if getattr(self, "show_llm_stdout", True):
            print(f'玩家 {self.name} 正在反思和总结...')
        # 生成当前轮次的对局历史
        action_history = self.get_action_history(game_state.action_history)
        # 生成结果信息
        result_str = game_result.get_result_info()
        # 生成所有玩家信息
        player_info = self.get_all_player_info(game_state)

        # 使用一次调用为所有玩家进行分析
        basePrompt = self._read_file(REFLECT_ALL_PROMPT_PATH)
        prompt = ""
        raw_response = ""
        try:
            prompt = basePrompt.format(
                self_name=self.player.name,
                user_info=player_info,
                action_history=action_history,
                game_result=result_str,
                previous_opinion=self.all_player_previous
            )
            response_with_metadata = self._call_llm_api_with_metadata(prompt)
            raw_response = response_with_metadata.get("content", "")
            content = raw_response
            # 更新对其他玩家的印象
            self.all_player_previous = content.strip()
            if getattr(self, "show_llm_stdout", True):
                print(f"{self.name} 更新了对其他玩家的印象: {content}")

            # 记录反思过程到日志
            if self.game_logger:
                self.game_logger.log_llm_reflection(
                    player_name=self.name,
                    model_name=self.model_name,
                    hand_number=game_state.hand_num,
                    prompt=prompt,
                    game_result=result_str,
                    raw_response=raw_response,
                    updated_opinions={"all_players": content}
                )
        except Exception as e:
            if getattr(self, "show_llm_stdout", True):
                print(f"反思自己时出错: {str(e)}")
            # 记录反思错误到日志
            if self.game_logger:
                self.game_logger.log_llm_reflection(
                    player_name=self.name,
                    model_name=self.model_name,
                    hand_number=game_state.hand_num,
                    prompt=prompt if prompt else "",
                    game_result=result_str,
                    raw_response=raw_response if raw_response else "",
                    updated_opinions={}
                )

    def _read_file(self, filepath: str) -> str:
        """读取文件内容"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            print(f"读取文件 {filepath} 失败: {str(e)}")
            return ""

    def get_self_current_round_info(self, game_state: GameInfoState) -> str:
        return f"""
        - 你的手牌：{', '.join(str(card) for card in self.player.hand)}
        - 你已下注：{self.player.bet_in_round}
        - 你的剩余筹码：{self.player.chips}
        - 你的位置：{game_state.position}
        """

    def get_all_player_info(self, game_state: GameInfoState) -> str:
        prompt = ''
        for i, player_info in enumerate(game_state.players_info):
            is_self = player_info.name == self.player.name
            position_str = "(你)" if is_self else ""
            dealer_str = "(庄家)" if i == game_state.dealer_position else ""
            prompt += f"- 玩家{position_str}{dealer_str}: {player_info.name},位置：{i}, 剩余筹码: {player_info.chips}, 已下注: {player_info.bet_in_round}, {'已弃牌' if player_info.folded else '未弃牌'}, {'已全押' if player_info.all_in else '未全押'}\n"
        return prompt

    def get_action_history(self, action_history: List[GameAction]) -> str:
        """获取当前轮次的对局历史"""
        action_history_str = ""
        for action in action_history:
            action_history_str += f"牌局阶段 {action.stage.value} 玩家 {action.player_name} 执行 {action.action.value}"
            if action.amount > 0:
                action_history_str += f", 金额: {action.amount}"
            action_history_str += f"\n玩家 {action.player_name} 的表现:{action.behavior}\n"
        return action_history_str

    def get_player_performance(self, players_info: List[Player]) -> str:
        prompt = ''
        for player in players_info:
            if player.name == self.player.name:
                continue
            previous_opinion = self.opinions.get(player.name, "还不了解这个玩家")
            prompt += f'玩家 {player.name}:{previous_opinion}\n'

        return prompt


class OpenAiLLMUser(LLMPlayer):

    def _call_llm_api(self, prompt: str) -> str:
        if self.client is None:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        # 每次都发送相同的原始prompt
        messages = [
            {"role": "user", "content": prompt}
        ]

        # print(f"玩家 LLM请求的提示语信息: {prompt}")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages
        )

        if response.choices:
            message = response.choices[0].message
            content = message.content if message.content else ""
            reasoning_content = getattr(message, "reasoning_content", "")
            if getattr(self, "show_llm_stdout", True):
                if reasoning_content != '':
                    print(f"LLM推理内容: {reasoning_content}")
                print(f"LLM回复内容: {content}")
            return content

    def _call_llm_api_with_metadata(self, prompt: str) -> Dict[str, str]:
        """调用OpenAI兼容接口，返回内容和推理内容"""
        if self.client is None:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages
            )
        except Exception as e:
            raise RuntimeError(
                f"OpenAI请求失败(model={self.model_name}, base_url={self.base_url}): {e}"
            ) from e

        if response.choices:
            message = response.choices[0].message
            content = message.content if message.content else ""
            reasoning_content = getattr(message, "reasoning_content", "")
            if getattr(self, "show_llm_stdout", True):
                if reasoning_content:
                    print(f"LLM推理内容: {reasoning_content}", flush=True)
                print(f"LLM回复内容: {content}", flush=True)
            return {
                "content": content,
                "reasoning_content": reasoning_content
            }

        return {"content": "", "reasoning_content": ""}


class AnthropicLLMUser(LLMPlayer):

    def _call_llm_api(self, prompt: str) -> str:
        if self.client is None:
            self.client = Anthropic(api_key=self.api_key, base_url=self.base_url)
        # 每次都发送相同的原始prompt
        messages = [
            {"role": "user", "content": prompt}
        ]

        # print(f"玩家 LLM请求的提示语信息: {prompt}")
        response = self.client.messages.create(
            max_tokens=1024,
            model=self.model_name,
            messages=messages
        )

        if response.content:
            message = response.content[0]
            content = message.text if message.text else ""
            if getattr(self, "show_llm_stdout", True):
                print(f"LLM推理内容: {content}")

            return content

    def _call_llm_api_with_metadata(self, prompt: str) -> Dict[str, str]:
        """调用Anthropic接口，返回内容"""
        if self.client is None:
            self.client = Anthropic(api_key=self.api_key, base_url=self.base_url)

        messages = [
            {"role": "user", "content": prompt}
        ]

        response = self.client.messages.create(
            max_tokens=1024,
            model=self.model_name,
            messages=messages
        )

        if response.content:
            message = response.content[0]
            content = message.text if message.text else ""
            if getattr(self, "show_llm_stdout", True):
                print(f"LLM回复内容: {content}", flush=True)
            return {
                "content": content,
                "reasoning_content": ""  # Anthropic不提供单独的推理内容字段
            }

        return {"content": "", "reasoning_content": ""}
