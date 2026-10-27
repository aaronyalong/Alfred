"""Shared plumbing for Claude calls: the client, usage and cost totals, and a disk cache.

Every call costs money, so each caller keeps a `Usage` and reports it. Results that are
expensive to repeat (a page's vision reading, a document's topic map) are saved in a
`DiskCache`, keyed by a hash of the exact request: a changed prompt or model never reuses
an old answer.
"""

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import anthropic
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, ValidationError

from alfred.config import get_settings

Effort = Literal["low", "medium", "high", "xhigh", "max"]

KEY_HINT = "Claude calls need ANTHROPIC_API_KEY (in the environment or .env)"

# If a safety classifier declines, the API retries on the model Anthropic recommends.
FALLBACK: dict[str, Any] = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

# USD per million tokens: input, output, cache write (5-minute), cache read. As of 2026-10.
_PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}


class LLMError(Exception):
    """A Claude call could not be made, e.g. no credentials. Messages can be shown as-is."""


def make_client() -> anthropic.Anthropic:
    key = get_settings().anthropic_api_key
    try:
        return anthropic.Anthropic(api_key=key.get_secret_value() if key else None)
    except anthropic.AnthropicError as e:  # no credentials found
        raise LLMError(f"{KEY_HINT}: {e}") from e


def final_text(message: BetaMessage) -> str:
    """The answer's text. After a fallback, earlier blocks may be the declined model's partial
    answer, so the last text block is the one that counts."""
    texts = [block.text for block in message.content if block.type == "text"]
    return texts[-1] if texts else ""


def request_key(**request: Any) -> str:
    """A stable hash of everything that shapes an answer, for use as a cache key."""
    payload = json.dumps(request, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class Usage:
    """Running totals over a set of calls. Safe to update from threads."""

    calls: int = 0
    cached: int = 0  # answers reused from a DiskCache, at no cost
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float | None = 0.0  # None once any call ran on a model with no known price
    served_by: set[str] = field(default_factory=set)  # differs from the request on a fallback
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_cached(self) -> None:
        with self._lock:
            self.cached += 1

    def add(self, message: BetaMessage) -> None:
        usage = message.usage
        tokens = (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_creation_input_tokens or 0,
            usage.cache_read_input_tokens or 0,
        )
        price = _PRICES.get(message.model)
        with self._lock:
            self.calls += 1
            self.input_tokens += tokens[0]
            self.output_tokens += tokens[1]
            self.cache_write_tokens += tokens[2]
            self.cache_read_tokens += tokens[3]
            self.served_by.add(message.model)
            if price is None or self.cost_usd is None:
                self.cost_usd = None
            else:
                self.cost_usd += sum(n * p for n, p in zip(tokens, price, strict=True)) / 1e6


class DiskCache:
    """Answers saved as JSON files, one per request key.

    The files contain text from course material, so the folder must stay git-ignored.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def get[M: BaseModel](self, key: str, model: type[M]) -> M | None:
        try:
            return model.model_validate_json(self._path(key).read_bytes())
        except (OSError, ValidationError):  # missing, or written by an older schema
            return None

    def put(self, key: str, value: BaseModel) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        # Write, then rename: a reader on another thread never sees a half-written file.
        temporary = self._path(key).with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(value.model_dump_json(), encoding="utf-8")
        temporary.replace(self._path(key))

    def _path(self, key: str) -> Path:
        return self._directory / f"{key}.json"


def default_cache(name: str) -> DiskCache:
    """The cache for one kind of answer, under the configured (git-ignored) cache folder."""
    return DiskCache(get_settings().alfred_cache_dir / name)
