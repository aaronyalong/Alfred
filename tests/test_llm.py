from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel

from alfred.llm import DiskCache, Usage, final_text, request_key


def message(model: str = "claude-opus-5-5", **tokens: int) -> BetaMessage:
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
        **tokens,
    }
    return cast(BetaMessage, SimpleNamespace(model=model, usage=SimpleNamespace(**usage)))


def test_usage_prices_every_kind_of_token() -> None:
    usage = Usage()

    usage.add(
        message(
            input_tokens=1_000,
            output_tokens=200,
            cache_creation_input_tokens=10_000,
            cache_read_input_tokens=20_000,
        )
    )

    expected = (1_000 * 4.00 + 200 * 20.00 + 10_000 * 5.00 + 20_000 * 0.20) / 1e6
    assert usage.cost_usd == pytest.approx(expected)
    assert (usage.calls, usage.cache_write_tokens, usage.cache_read_tokens) == (1, 10_000, 20_000)


def test_cost_is_unknown_once_a_call_ran_on_an_unpriced_model() -> None:
    usage = Usage()

    usage.add(message(input_tokens=1_000))
    usage.add(message("some-fallback-model", input_tokens=1_000))

    assert usage.cost_usd is None
    assert usage.served_by == {"claude-opus-5-5", "some-fallback-model"}


def test_final_text_is_the_last_text_block() -> None:
    blocks: list[Any] = [
        SimpleNamespace(type="text", text="partial answer from the declined model"),
        SimpleNamespace(type="fallback"),
        SimpleNamespace(type="text", text="the answer"),
    ]

    assert final_text(cast(BetaMessage, SimpleNamespace(content=blocks))) == "the answer"


class Answer(BaseModel):
    value: int


def test_disk_cache_round_trips_and_misses_on_bad_files(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    key = request_key(model="m", prompt="p")

    assert cache.get(key, Answer) is None
    cache.put(key, Answer(value=3))
    assert cache.get(key, Answer) == Answer(value=3)
    (tmp_path / "cache" / f"{key}.json").write_text("{broken", encoding="utf-8")
    assert cache.get(key, Answer) is None


def test_request_keys_change_with_any_part_of_the_request() -> None:
    assert request_key(model="a", prompt="p") == request_key(prompt="p", model="a")
    assert request_key(model="a", prompt="p") != request_key(model="b", prompt="p")
