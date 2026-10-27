"""A stand-in for the Anthropic client, so tests never make real (paid) calls."""

from types import SimpleNamespace
from typing import Any, cast

import anthropic


class FakeClaude:
    """Records every request and answers with the given replies in order; the last repeats."""

    def __init__(
        self,
        *replies: str,
        stop_reason: str = "end_turn",
        model: str = "claude-opus-5-5",
        input_tokens: int = 1_000,
        output_tokens: int = 200,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self._replies = list(replies) or ['{"blocks": []}']
        self._stop_reason = stop_reason
        self._model = model
        self._tokens = (input_tokens, output_tokens)
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=self._create, stream=self._stream)
        )

    @property
    def client(self) -> anthropic.Anthropic:
        return cast(anthropic.Anthropic, self)

    def _create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        return self._message()

    def _stream(self, **request: Any) -> "_Stream":
        self.requests.append(request)
        return _Stream(self._message())

    def _message(self) -> SimpleNamespace:
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        return SimpleNamespace(
            model=self._model,
            stop_reason=self._stop_reason,
            usage=SimpleNamespace(
                input_tokens=self._tokens[0],
                output_tokens=self._tokens[1],
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
            content=[SimpleNamespace(type="text", text=reply)],
        )


class _Stream:
    def __init__(self, message: SimpleNamespace) -> None:
        self._message = message

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_final_message(self) -> SimpleNamespace:
        return self._message
