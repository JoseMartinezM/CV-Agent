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

        for model in self.models:
            try:
                r = self.client.models.generate_content(model=model, contents=contents, config=config)
                break
            except errors.APIError as e:
                if e.code not in RETRY_ON or model == self.models[-1]:
                    raise

        usage = r.usage_metadata
        thoughts = (usage.thoughts_token_count or 0) if usage else 0
        finish = r.candidates[0].finish_reason if r.candidates else None
        return LLMResult(
            text=r.text or "",
            model=model,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=((usage.candidates_token_count or 0) + thoughts) if usage else 0,
            reasoning_tokens=thoughts,
            truncated=finish == types.FinishReason.MAX_TOKENS,
        )
