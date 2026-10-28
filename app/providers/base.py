from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0  # includes reasoning tokens
    reasoning_tokens: int = 0
    truncated: bool = False  # hit max_output_tokens


class LLMProvider(Protocol):
    def generate(
        self,
        system: str,
        turns: list[Turn],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult: ...

    def stream(
        self,
        system: str,
        turns: list[Turn],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str | LLMResult]:
        """Yields text chunks, then one LLMResult at the end."""
        ...
