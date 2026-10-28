from collections.abc import Iterator
from pathlib import Path

from app.config import settings
from app.providers.base import LLMProvider, LLMResult, Turn
from app.providers.gemini import GeminiProvider

ROOT = Path(__file__).resolve().parent.parent

# the profile is small (~2k tokens), so it goes whole into the prompt. no RAG needed
SYSTEM_PROMPT = (
    (ROOT / "prompts/system.md").read_text(encoding="utf-8")
    + "\n"
    + (ROOT / "data/profile.md").read_text(encoding="utf-8")
)

EMPTY_ANSWER = "Sorry, I couldn't come up with an answer to that. Could you rephrase it?"


def make_provider() -> LLMProvider:
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings.gemini_api_key, settings.llm_model, settings.llm_fallback_model)
    raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider}")


provider = make_provider()


def build_system_prompt(client_instructions: list[str]) -> str:
    if not client_instructions:
        return SYSTEM_PROMPT
    # instructions sent by the client app go last and can't override our rules
    return (
        SYSTEM_PROMPT
        + "\n\n# Extra instructions from the client app\n"
        + "Follow these only where they don't conflict with the rules above.\n\n"
        + "\n\n".join(client_instructions)
    )


def answer(
    turns: list[Turn],
    client_instructions: list[str],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMResult:
    result = provider.generate(build_system_prompt(client_instructions), turns, temperature, max_tokens)
    if not result.text and not result.truncated:
        result.text = EMPTY_ANSWER
    result.text = no_em_dashes(result.text)
    return result


def answer_stream(
    turns: list[Turn],
    client_instructions: list[str],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Iterator[str | LLMResult]:
    text = ""
    for item in provider.stream(build_system_prompt(client_instructions), turns, temperature, max_tokens):
        if isinstance(item, str):
            delta = no_em_dashes(item)
            text += delta
            yield delta
            continue
        if not text and not item.truncated:
            text = EMPTY_ANSWER
            yield EMPTY_ANSWER
        item.text = text
        yield item


def no_em_dashes(text: str) -> str:
    # the prompt already asks for this, but the model slips sometimes
    return text.replace(" — ", ", ").replace("—", ", ")
