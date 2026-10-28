import base64
import binascii
import json
import time
import uuid
from collections.abc import Iterator
from itertools import count
from typing import Any

from app.providers.base import LLMOptions, LLMResult, Turn
from app.schemas import (
    CreateResponseRequest,
    FunctionCall,
    OutputMessage,
    OutputText,
    OutputTokensDetails,
    ResponseError,
    ResponseResource,
    Usage,
)

TEXT_PARTS = {"input_text", "output_text", "text"}


class APIError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        type: str = "invalid_request_error",
        code: str | None = None,
        param: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.type = type
        self.code = code
        self.param = param


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ponytail: in-memory store for previous_response_id. lost on restart and not shared
# between instances, so cloud run runs with max-instances=1. a db if it ever scales
_history: dict[str, list[Turn]] = {}
MAX_STORED = 500


def save_history(response_id: str, turns: list[Turn], answer: str) -> None:
    _history[response_id] = turns + [Turn("assistant", answer)]
    if len(_history) > MAX_STORED:
        _history.pop(next(iter(_history)))


def parse_content(content: Any) -> tuple[str, list[str]]:
    """Returns (text, image data urls)."""
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        raise APIError(400, "message content must be a string or a list of content parts", param="input")
    texts = []
    images = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in TEXT_PARTS and "text" in part:
            texts.append(part["text"])
        elif part.get("type") == "input_image":
            images.append(check_image(part.get("image_url")))
    return "\n".join(texts), images


def check_image(url: Any) -> str:
    # ponytail: only inline base64 images. fetching http urls means downloading
    # whatever a stranger points us at, not worth it for a cv agent
    if not isinstance(url, str) or not url.startswith("data:image/") or ";base64," not in url:
        raise APIError(400, "only base64 data: URLs are supported for input_image", param="input")
    try:
        base64.b64decode(url.split(",", 1)[1], validate=True)
    except binascii.Error:
        raise APIError(400, "input_image has invalid base64 data", param="input")
    return url


def tool_output_text(output: Any) -> str:
    return output if isinstance(output, str) else parse_content(output)[0]


def normalize_input(req: CreateResponseRequest) -> tuple[list[str], list[Turn]]:
    """Split the request into (client instructions, conversation turns)."""
    instructions = [req.instructions] if req.instructions else []
    turns: list[Turn] = []

    if req.previous_response_id:
        if req.previous_response_id not in _history:
            raise APIError(
                404,
                f"previous response '{req.previous_response_id}' not found",
                type="not_found",
                code="previous_response_not_found",
                param="previous_response_id",
            )
        turns = list(_history[req.previous_response_id])

    if isinstance(req.input, str):
        turns.append(Turn("user", req.input))
    else:
        for item in req.input or []:
            # messages can come without "type", the spec allows the short form
            kind = item.get("type", "message")
            if kind == "message":
                role = item.get("role")
                text, images = parse_content(item.get("content", ""))
                if role in ("system", "developer"):
                    instructions.append(text)
                elif role in ("user", "assistant"):
                    turns.append(Turn(role, text, images))
            # client tool round trips go to the model as plain text, simpler than
            # rebuilding gemini function call parts (and their thought signatures)
            elif kind == "function_call":
                turns.append(Turn("assistant", f"[called tool {item.get('name')} with {item.get('arguments')}]"))
            elif kind == "function_call_output":
                output = tool_output_text(item.get("output", ""))
                turns.append(Turn("user", f"[result of tool call {item.get('call_id')}]: {output}"))
            # reasoning, item_reference, etc. are skipped

    if not any(t.role == "user" for t in turns):
        raise APIError(400, "input must include at least one user message", param="input")
    return instructions, turns


def options_from(req: CreateResponseRequest) -> LLMOptions:
    return LLMOptions(
        temperature=req.temperature,
        max_tokens=req.max_output_tokens,
        tools=req.tools or [],
        tool_choice=req.tool_choice,
    )


def base_response(req: CreateResponseRequest, response_id: str, created_at: int, model: str) -> ResponseResource:
    # the in_progress snapshot, also used as the starting point for the final one
    return ResponseResource(
        id=response_id,
        created_at=created_at,
        status="in_progress",
        model=model,
        previous_response_id=req.previous_response_id,
        instructions=req.instructions,
        tools=[{"description": None, "parameters": None, "strict": True, **t} for t in req.tools or []],
        tool_choice=req.tool_choice or "auto",
        temperature=req.temperature if req.temperature is not None else 1.0,
        top_p=req.top_p if req.top_p is not None else 1.0,
        max_output_tokens=req.max_output_tokens,
        store=True,
        metadata=req.metadata or {},
    )


def finish_response(
    base: ResponseResource, result: LLMResult, msg_id: str, keep_empty_message: bool = False
) -> ResponseResource:
    status = "incomplete" if result.truncated else "completed"
    output: list[OutputMessage | FunctionCall] = []
    # a tool call usually comes with no text, skip the empty message then.
    # streaming already announced the message, so it has to stay there
    if result.text or not result.tool_calls or keep_empty_message:
        output.append(OutputMessage(id=msg_id, status=status, content=[OutputText(text=result.text)]))
    for call in result.tool_calls:
        output.append(FunctionCall(id=new_id("fc"), call_id=new_id("call"), name=call.name, arguments=call.arguments))
    return base.model_copy(
        update={
            "status": status,
            "model": result.model,
            "completed_at": int(time.time()) if status == "completed" else None,
            "incomplete_details": {"reason": "max_output_tokens"} if result.truncated else None,
            "output": output,
            "usage": Usage(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.input_tokens + result.output_tokens,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=result.reasoning_tokens),
            ),
        }
    )


def as_api_error(e: Exception) -> APIError:
    if isinstance(e, APIError):
        return e
    if getattr(e, "code", None) == 429:  # gemini quota
        return APIError(429, "The model is out of quota, try again in a minute", type="too_many_requests")
    return APIError(500, "The model failed to answer, try again", type="model_error")


def sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def stream_events(
    req: CreateResponseRequest,
    response_id: str,
    created_at: int,
    model: str,
    chunks: Iterator[str | LLMResult],
) -> Iterator[str]:
    seq = count()
    msg_id = new_id("msg")
    where = {"item_id": msg_id, "output_index": 0, "content_index": 0}

    def event(type: str, **fields: Any) -> str:
        return sse({"type": type, "sequence_number": next(seq), **fields})

    base = base_response(req, response_id, created_at, model)
    yield event("response.created", response=base.model_dump())
    yield event("response.in_progress", response=base.model_dump())
    item = OutputMessage(id=msg_id, status="in_progress", content=[])
    yield event("response.output_item.added", output_index=0, item=item.model_dump())
    yield event("response.content_part.added", **where, part=OutputText(text="").model_dump())

    try:
        for chunk in chunks:
            if isinstance(chunk, str):
                yield event("response.output_text.delta", **where, delta=chunk, logprobs=[])
            else:
                result = chunk
    except Exception as e:
        # headers are already sent, so errors go as events. spec says error then response.failed
        err = as_api_error(e)
        yield event("error", error={"type": err.type, "code": err.code, "message": err.message, "param": err.param})
        failed = base.model_copy(
            update={"status": "failed", "error": ResponseError(code=err.code or err.type, message=err.message)}
        )
        yield event("response.failed", response=failed.model_dump())
        return

    final = finish_response(base, result, msg_id, keep_empty_message=True)
    message = final.output[0]
    yield event("response.output_text.done", **where, text=result.text, logprobs=[])
    yield event("response.content_part.done", **where, part=message.content[0].model_dump())
    yield event("response.output_item.done", output_index=0, item=message.model_dump())

    # gemini hands over tool calls whole, so the arguments go in a single delta
    for index, call in enumerate(final.output[1:], start=1):
        started = call.model_copy(update={"status": "in_progress", "arguments": ""})
        yield event("response.output_item.added", output_index=index, item=started.model_dump())
        yield event("response.function_call_arguments.delta", item_id=call.id, output_index=index, delta=call.arguments)
        yield event("response.function_call_arguments.done", item_id=call.id, output_index=index, arguments=call.arguments)
        yield event("response.output_item.done", output_index=index, item=call.model_dump())
    terminal = "response.incomplete" if final.status == "incomplete" else "response.completed"
    yield event(terminal, response=final.model_dump())
