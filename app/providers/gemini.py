import base64
import json
from collections.abc import Iterator
from itertools import chain
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.providers.base import LLMOptions, LLMResult, ToolCall, Turn

# the free tier throws these a lot when a model is busy, worth trying the fallback
RETRY_ON = {429, 500, 503, 504}
# normal answers take 2 to 12 s on the free tier, past this the call is likely stuck
TIMEOUT_MS = 30_000


class GeminiProvider:
    def __init__(self, api_key: str, model: str, fallback_model: str = ""):
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
        self.models = [model]
        if fallback_model and fallback_model != model:
            self.models.append(fallback_model)

    def generate(self, system: str, turns: list[Turn], options: LLMOptions) -> LLMResult:
        config, contents = build_request(system, turns, options)
        for model in self.models:
            try:
                r = self.client.models.generate_content(model=model, contents=contents, config=config)
                break
            except (errors.APIError, httpx.TimeoutException) as e:
                if not worth_retrying(e) or model == self.models[-1]:
                    raise
                log_fallback(model, e)
        text, calls = read_parts(r)
        return to_result(r, text, calls, model)

    def stream(self, system: str, turns: list[Turn], options: LLMOptions) -> Iterator[str | LLMResult]:
        config, contents = build_request(system, turns, options)
        for model in self.models:
            try:
                chunks = self.client.models.generate_content_stream(model=model, contents=contents, config=config)
                # errors show up on the first chunk, not on the call, so pull it here
                # to still be able to switch models before sending anything
                first = next(chunks, None)
                break
            except (errors.APIError, httpx.TimeoutException) as e:
                if not worth_retrying(e) or model == self.models[-1]:
                    raise
                log_fallback(model, e)

        text = ""
        calls: list[ToolCall] = []
        last = first
        for chunk in chain([first], chunks) if first else []:
            last = chunk
            delta, chunk_calls = read_parts(chunk)
            calls += chunk_calls
            if delta:
                text += delta
                yield delta
        yield to_result(last, text, calls, model)


def worth_retrying(e: Exception) -> bool:
    return isinstance(e, httpx.TimeoutException) or e.code in RETRY_ON


def log_fallback(model: str, e: Exception) -> None:
    # same json line format as main.log, so it shows up next to the request logs
    print(json.dumps({"severity": "WARNING", "event": "model_fallback", "model": model, "error": repr(e)[:300]}), flush=True)


def build_request(
    system: str, turns: list[Turn], options: LLMOptions
) -> tuple[types.GenerateContentConfig, list[types.Content]]:
    functions = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description") or "",
            parameters_json_schema=t.get("parameters"),
        )
        for t in options.tools
        if t.get("type") == "function" and t.get("name")
    ]
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=options.temperature,
        max_output_tokens=options.max_tokens,
        # answers are short lookups in the profile. more thinking tripled latency
        # without changing eval results, and it eats into max_output_tokens
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
        tools=[types.Tool(function_declarations=functions)] if functions else None,
        tool_config=tool_config(options.tool_choice) if functions else None,
    )
    return config, [to_content(t) for t in turns]


def to_content(turn: Turn) -> types.Content:
    parts = []
    if turn.text or not turn.images:
        parts.append(types.Part.from_text(text=turn.text))
    for url in turn.images:
        header, data = url.split(",", 1)  # data:image/png;base64,....
        mime = header.removeprefix("data:").split(";")[0]
        parts.append(types.Part.from_bytes(data=base64.b64decode(data), mime_type=mime))
    return types.Content(role="model" if turn.role == "assistant" else "user", parts=parts)


def tool_config(choice: str | dict[str, Any] | None) -> types.ToolConfig | None:
    mode = types.FunctionCallingConfigMode
    if choice == "none":
        config = types.FunctionCallingConfig(mode=mode.NONE)
    elif choice == "required":
        config = types.FunctionCallingConfig(mode=mode.ANY)
    elif isinstance(choice, dict) and choice.get("type") == "function":
        config = types.FunctionCallingConfig(mode=mode.ANY, allowed_function_names=[choice["name"]])
    elif isinstance(choice, dict) and choice.get("type") == "allowed_tools":
        names = [t["name"] for t in choice.get("tools", []) if t.get("name")]
        forced = choice.get("mode") == "required"
        config = types.FunctionCallingConfig(mode=mode.ANY if forced else mode.AUTO, allowed_function_names=names)
    else:
        return None
    return types.ToolConfig(function_calling_config=config)


def read_parts(r: types.GenerateContentResponse | None) -> tuple[str, list[ToolCall]]:
    # going through parts by hand because r.text warns when there are function calls
    if not r or not r.candidates or not r.candidates[0].content:
        return "", []
    text = ""
    calls = []
    for p in r.candidates[0].content.parts or []:
        if p.thought:
            continue
        if p.text:
            text += p.text
        if p.function_call:
            calls.append(ToolCall(p.function_call.name, json.dumps(p.function_call.args or {})))
    return text, calls


def to_result(
    r: types.GenerateContentResponse | None, text: str, calls: list[ToolCall], model: str
) -> LLMResult:
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
        tool_calls=calls,
    )
