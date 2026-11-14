"""Group reply selection and a rolling limit for optional interjections.

Only ``group_reply_mode=adaptive`` enables this policy.  The caller keeps its
existing private-chat behavior, delivers *all* incoming group events to AstrBot,
and uses the decision only to select which events should wake the model.

Name-based addressing is deliberately a local heuristic, not a semantic model:
it recognizes explicit mentions, forms of address and explicit requests.  It
cannot reliably decide whom an implicit follow-up such as ``那你怎么看`` refers
to in a conversation between several people.

``send_slot`` must surround one optional outgoing operation, not a direct reply.
A granted slot is counted when its body finishes, including exceptions, because
an unsuccessful transport can leave delivery unconfirmed.  It never retries.
The state is process-local and intended for the adapter's one asyncio loop.
"""

from __future__ import annotations

import asyncio
import math
import random
import re
import time
import unicodedata
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal


def parse_bool(value: Any, default: bool = False) -> bool:
    """Read a JSON boolean or an explicit legacy textual boolean safely."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return default


def _number(value: Any, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(maximum, max(minimum, parsed))


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", normalized).strip().casefold()


@dataclass(frozen=True, slots=True)
class GroupReplyDecision:
    kind: Literal["direct", "spontaneous", "silent"]
    reason: str


@dataclass(slots=True)
class _GroupState:
    completed_attempts: deque[float] = field(default_factory=deque)
    last_selected: float | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class GroupReplyPolicy:
    """Choose group replies without dropping quiet messages from the event bus.

    Numeric settings accept JSON numbers and legacy numeric strings. Probability
    is clamped to [0, 1], the per-minute limit to [0, 10], and the selection gap to
    [0, 3600] seconds. Zero probability or a zero limit disables interjections;
    direct addressing remains eligible. Invalid values use documented defaults.
    """

    WINDOW_SECONDS = 60.0

    def __init__(
        self,
        config: dict[str, Any],
        self_id: str,
        nickname: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.enabled = str(config.get("group_reply_mode", "legacy")).strip().casefold() == "adaptive"
        self.self_id = str(self_id).strip()
        self.probability = _number(config.get("group_interject_probability", 0.6), 0.6, 0.0, 1.0)
        self.max_per_minute = int(
            _number(config.get("group_interject_max_per_minute", 10), 10.0, 0.0, 10.0)
        )
        self.min_interval_seconds = _number(
            config.get("group_interject_min_interval_seconds", 5), 5.0, 0.0, 3600.0
        )
        configured = config.get("group_bot_aliases", ["大肥鱼"])
        if not isinstance(configured, (list, tuple)):
            configured = ["大肥鱼"]
        self._configured_aliases = tuple(
            alias for value in configured
            if isinstance(value, str) and (alias := _normalize(value))
        ) or ("大肥鱼",)
        self._aliases: tuple[str, ...] = ()
        self.set_nickname(nickname)
        self._clock = clock
        self._rng = rng
        self._groups: dict[str, _GroupState] = {}

    @property
    def aliases(self) -> tuple[str, ...]:
        return self._aliases

    def set_nickname(self, name: str | None) -> None:
        aliases = set(self._configured_aliases)
        if isinstance(name, str) and (normalized := _normalize(name)):
            aliases.add(normalized)
        self._aliases = tuple(sorted(aliases, key=lambda item: (-len(item), item)))
        alternatives = "|".join(re.escape(alias) for alias in self._aliases)
        # A parenthesis admits a group nickname suffix such as 大肥鱼(昵称).
        boundary = r"(?=$|[\s,.:;!?、，。！？：；()\[\]{}<>《》])"
        self._text_mention = re.compile(r"@\s*(?:" + alternatives + r")" + boundary)
        self._name_at_start = re.compile(
            r"^(?:(?:嗨|嘿|喂|你好|hello|hi)[\s,!:：，]*)?"
            r"(?P<alias>" + alternatives + r")(?P<rest>.*)$"
        )
        self._request_before_name = re.compile(
            r"(?:请问|请教|想问|问问|问下|问一下|问一问|麻烦|拜托|请)"
            r"\s*(?:一下|下|一下子)?\s*(?:" + alternatives + r")"
        )
        self._name_after_punctuation = re.compile(
            r"(?:^|[\s,，;；:：!?！？])(?:" + alternatives + r")\s*"
            r"(?:你|您|能不能|可不可以|会不会|帮我|帮我们|请|来回答|来解释)"
        )
        self._name_at_end = re.compile(
            r"^(?P<body>.+?)[,，:：]\s*(?:" + alternatives + r")"
            r"(?:\([^()\n]*\))?\s*[?!.。！？]*$"
        )

    def _identity_matches(self, candidate: Any) -> bool:
        if not isinstance(candidate, (str, int)) or isinstance(candidate, bool):
            return False
        text = str(candidate).strip()
        if self.self_id and text == self.self_id:
            return True
        normalized = _normalize(text)
        return any(
            normalized == alias
            or (normalized.startswith(alias + "(") and normalized.endswith(")"))
            or (normalized.startswith(alias + " (") and normalized.endswith(")"))
            for alias in self._aliases
        )

    def _metadata_mentions_self(self, data: dict[str, Any]) -> bool:
        if any(parse_bool(data.get(key)) for key in ("is_at_me", "mentioned_me", "at_me")):
            return True
        for key in ("mentioned_users", "mentions", "at_list"):
            entries = data.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if self._identity_matches(entry):
                    return True
                if isinstance(entry, dict) and any(
                    self._identity_matches(entry.get(field))
                    for field in ("username", "user_id", "id", "qq", "wxid", "nickname", "display_name", "name")
                ):
                    return True
        return False

    @staticmethod
    def _is_question_or_request(text: str) -> bool:
        return bool(re.search(
            r"[?？]|(?:吗|么|呢|嘛)[。.!！\s]*$|怎么|怎样|如何|为什么|为何|多少|什么|哪个|哪种|"
            r"是否|有没有|能不能|可不可以|会不会|行不行|好不好|你觉得|你认为|你说|"
            r"帮我|帮我们|请|解释|回答|说说|讲讲|告诉|看看|看下|推荐|总结|分析|翻译",
            text,
        ))

    def _direct_reason(self, text: str, data: dict[str, Any]) -> str | None:
        if self._metadata_mentions_self(data):
            return "mention_metadata"
        if not text:
            return None
        # AstrBot commands are requests, not unsolicited conversation. Keep
        # command replies working even when the optional-reply quota is full.
        if re.match(r"^/[a-z_][\w-]*(?:\s|$)", text):
            return "explicit_command"
        if self._text_mention.search(text):
            return "mention_text"
        if self._request_before_name.search(text):
            return "explicit_request"
        if self._name_after_punctuation.search(text):
            return "addressed_by_name"
        ending = self._name_at_end.match(text)
        if ending and self._is_question_or_request(ending.group("body")):
            return "name_suffix_question"

        start = self._name_at_start.match(text)
        if not start:
            return None
        rest = start.group("rest")
        # Strip a decorative nickname suffix before reading the actual request.
        rest = re.sub(r"^\s*\([^()\n]*\)", "", rest, count=1)
        if not rest.strip():
            return "name_call"
        # A comma/colon, or punctuation-only ending, is a form of address.
        if re.match(r"^\s*[,，:：]", rest) or re.fullmatch(r"[\s!?！？。.]+", rest):
            return "addressed_by_name"
        rest = rest.strip()
        # These are usually reports *about* the bot, not requests *to* it.
        if re.match(
            r"^(?:昨天|刚刚|刚才|以前|之前|上次|曾经|已经|"
            r"(?:说|回答|解释|推荐|总结|分析|翻译)(?:过|了|得)|"
            r"的(?:回答|解释|推荐|总结|分析|翻译))",
            rest,
        ):
            return None
        if re.match(r"^(?:你|您|能不能|可不可以|会不会|帮我|帮我们|给我|给我们|请|来回答|来解释|用语音|发条语音|语音(?:回|讲|说))", rest):
            return "addressed_by_name"
        if self._is_question_or_request(rest):
            return "named_question_or_request"
        return None

    def _state(self, group_id: str) -> _GroupState:
        key = str(group_id)
        state = self._groups.get(key)
        if state is None:
            state = _GroupState()
            self._groups[key] = state
        return state

    def _prune(self, state: _GroupState, now: float) -> None:
        while state.completed_attempts and now - state.completed_attempts[0] >= self.WINDOW_SECONDS:
            state.completed_attempts.popleft()

    def remaining_count(self, group_id: str) -> int:
        """Return available optional send attempts in the current 60s window."""
        if not self.enabled or not str(group_id).strip():
            return 0
        state = self._state(group_id)
        self._prune(state, self._clock())
        return max(0, self.max_per_minute - len(state.completed_attempts))

    def can_interject(self, group_id: str) -> bool:
        """Check quota and selection gap without drawing randomness or reserving."""
        if not self.enabled or self.probability <= 0 or not str(group_id).strip():
            return False
        state = self._state(group_id)
        now = self._clock()
        self._prune(state, now)
        return (
            len(state.completed_attempts) < self.max_per_minute
            and (state.last_selected is None or now - state.last_selected >= self.min_interval_seconds)
        )

    def decide(self, group_id: str, text: str, data: dict[str, Any]) -> GroupReplyDecision:
        """Select one already-deduplicated incoming group message.

        A silent result is not a request to discard the event.  The adapter must
        still commit it so that group-context and memory handlers can observe it.
        """
        if not self.enabled:
            return GroupReplyDecision("silent", "policy_disabled")
        normalized = _normalize(text) if isinstance(text, str) else ""
        metadata = data if isinstance(data, dict) else {}
        direct_reason = self._direct_reason(normalized, metadata)
        if direct_reason:
            return GroupReplyDecision("direct", direct_reason)
        if not str(group_id).strip():
            return GroupReplyDecision("silent", "invalid_group")
        if not normalized:
            return GroupReplyDecision("silent", "empty_message")
        state = self._state(group_id)
        now = self._clock()
        self._prune(state, now)
        if len(state.completed_attempts) >= self.max_per_minute:
            return GroupReplyDecision("silent", "quota")
        if state.last_selected is not None and now - state.last_selected < self.min_interval_seconds:
            return GroupReplyDecision("silent", "selection_interval")
        if self.probability <= 0 or self._rng() >= self.probability:
            return GroupReplyDecision("silent", "probability")
        state.last_selected = now
        return GroupReplyDecision("spontaneous", "sampled")

    @asynccontextmanager
    async def send_slot(self, group_id: str) -> AsyncIterator[bool]:
        """Hold a per-group slot across exactly one optional native send.

        The caller must not invoke its sender when this yields False.  Direct
        replies and private chats must bypass this method.  Any entered True
        body counts once on completion, even if it raises or is cancelled.
        """
        if not self.enabled or not str(group_id).strip():
            yield False
            return
        state = self._state(group_id)
        async with state.send_lock:
            self._prune(state, self._clock())
            if len(state.completed_attempts) >= self.max_per_minute:
                yield False
                return
            try:
                yield True
            finally:
                state.completed_attempts.append(self._clock())
