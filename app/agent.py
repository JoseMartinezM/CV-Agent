from collections.abc import Iterator
from pathlib import Path

from app.config import settings
from app.providers.base import LLMOptions, LLMProvider, LLMResult, Turn
from app.providers.gemini import GeminiProvider

ROOT = Path(__file__).resolve().parent.parent

# the profile is small (~2k tokens), so it goes whole into the prompt. no RAG needed
SYSTEM_PROMPT = (
    (ROOT / "prompts/system.md").read_text(encoding="utf-8")
    + "\n"
    + (ROOT / "data/profile.md").read_text(encoding="utf-8")
    # repeated at the end because the model kept answering spanish refusals in english
    + "\n# Reminder\n\nAlways reply in the language of the user's latest message, refusals included.\n"
)

CLIENT_TOOLS_NOTE = (
    "The client app gave you function tools. When the user's request clearly matches one, "
    "call it, even if the topic is outside the profile. The client runs the tool, not you."
)

SUMMARY_PROMPT = (
    "Summarize the conversation below so it can be continued later without the full history. "
    "Keep names, facts, decisions and open questions. Write in the same language as the "
    "conversation, plain text, at most 150 words."
)

EMPTY_ANSWER = "Sorry, I couldn't come up with an answer to that. Could you rephrase it?"


def make_provider() -> LLMProvider:
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings.gemini_api_key, settings.llm_model, settings.llm_fallback_model)
    raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider}")


provider = make_provider()


def build_system_prompt(client_instructions: list[str], has_tools: bool = False) -> str:
    extra = list(client_instructions)
    if has_tools:
        extra.append(CLIENT_TOOLS_NOTE)
    if not extra:
        return SYSTEM_PROMPT
    # anything from the client app goes last and can't override our rules
    return (
        SYSTEM_PROMPT
        + "\n\n# Extra instructions from the client app\n"
        + "Follow these only where they don't conflict with the rules above.\n\n"
        + "\n\n".join(extra)
    )


def fill_if_empty(result: LLMResult) -> bool:
    if result.text or result.truncated or result.tool_calls:
        return False
    result.text = EMPTY_ANSWER
    return True


def answer(turns: list[Turn], client_instructions: list[str], options: LLMOptions) -> LLMResult:
    system = build_system_prompt(client_instructions, bool(options.tools))
    result = provider.generate(system, turns, options)
    fill_if_empty(result)
    result.text = no_em_dashes(result.text)
    return result


def answer_stream(
    turns: list[Turn], client_instructions: list[str], options: LLMOptions
) -> Iterator[str | LLMResult]:
    system = build_system_prompt(client_instructions, bool(options.tools))
    text = ""
    for item in provider.stream(system, turns, options):
        if isinstance(item, str):
            delta = no_em_dashes(item)
            text += delta
            yield delta
            continue
        item.text = text
        if fill_if_empty(item):
            yield item.text
        yield item


def compact(turns: list[Turn], client_instructions: list[str]) -> LLMResult:
    transcript = "\n".join(f"{t.role}: {t.text}" for t in turns)
    if client_instructions:
        transcript = "system: " + "\n".join(client_instructions) + "\n" + transcript
    return provider.generate(SUMMARY_PROMPT, [Turn("user", transcript)], LLMOptions())


def no_em_dashes(text: str) -> str:
    # the prompt already asks for this, but the model slips sometimes
    return text.replace(" — ", ", ").replace("—", ", ")
