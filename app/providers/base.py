from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str
    images: list[str] = field(default_factory=list)  # data: urls


@dataclass
class ToolCall:
    name: str
    arguments: str  # json string


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0  # includes reasoning tokens
    reasoning_tokens: int = 0
    truncated: bool = False  # hit max_output_tokens
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class LLMOptions:
    temperature: float | None = None
    max_tokens: int | None = None
    # function tools sent by the client, in open responses format
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None


class LLMProvider(Protocol):
    def generate(self, system: str, turns: list[Turn], options: LLMOptions) -> LLMResult: ...

    def stream(self, system: str, turns: list[Turn], options: LLMOptions) -> Iterator[str | LLMResult]:
        """Yields text chunks, then one LLMResult at the end."""
        ...
