from collections.abc import Iterator
from itertools import chain

from google import genai
from google.genai import errors, types

from app.providers.base import LLMResult, Turn

# the free tier throws these a lot when a model is busy, worth trying the fallback
RETRY_ON = {429, 500, 503}


class GeminiProvider:
    def __init__(self, api_key: str, model: str, fallback_model: str = ""):
        self.client = genai.Client(api_key=api_key)
        self.models = [model]
        if fallback_model and fallback_model != model:
            self.models.append(fallback_model)

    def generate(
        self,
        system: str,
        turns: list[Turn],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        config, contents = build_request(system, turns, temperature, max_tokens)
        for model in self.models:
            try:
                r = self.client.models.generate_content(model=model, contents=contents, config=config)
                break
            except errors.APIError as e:
                if e.code not in RETRY_ON or model == self.models[-1]:
                    raise
        return to_result(r, r.text or "", model)

    def stream(
        self,
        system: str,
        turns: list[Turn],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str | LLMResult]:
        config, contents = build_request(system, turns, temperature, max_tokens)
        for model in self.models:
            try:
                chunks = self.client.models.generate_content_stream(model=model, contents=contents, config=config)
                # errors show up on the first chunk, not on the call, so pull it here
                # to still be able to switch models before sending anything
                first = next(chunks, None)
                break
            except errors.APIError as e:
                if e.code not in RETRY_ON or model == self.models[-1]:
                    raise

        text = ""
        last = first
        for chunk in chain([first], chunks) if first else []:
            last = chunk
            if chunk.text:
                text += chunk.text
                yield chunk.text
        yield to_result(last, text, model)


def build_request(
    system: str, turns: list[Turn], temperature: float | None, max_tokens: int | None
) -> tuple[types.GenerateContentConfig, list[types.Content]]:
    # gemini counts thinking tokens inside max_output_tokens, so with a small
    # limit the whole budget goes to thinking and the answer comes back empty
    thinking = "minimal" if max_tokens else "low"
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_level=thinking),
    )
    contents = [
        types.Content(
            role="model" if t.role == "assistant" else "user",
            parts=[types.Part.from_text(text=t.text)],
        )
        for t in turns
    ]
    return config, contents


def to_result(r: types.GenerateContentResponse | None, text: str, model: str) -> LLMResult:
    # when streaming, usage and finish_reason only come in the last chunk
    usage = r.usage_metadata if r else None
    thoughts = (usage.thoughts_token_count or 0) if usage else 0
    finish = r.candidates[0].finish_reason if r and r.candidates else None
    return LLMResult(
        text=text,
        model=model,
        input_tokens=(usage.prompt_token_count or 0) if usage else 0,
        output_tokens=((usage.candidates_token_count or 0) + thoughts) if usage else 0,
        reasoning_tokens=thoughts,
        truncated=finish == types.FinishReason.MAX_TOKENS,
    )
