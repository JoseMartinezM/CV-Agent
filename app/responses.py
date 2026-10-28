import json
import time
import uuid
from collections.abc import Iterator
from itertools import count
from typing import Any

from app.providers.base import LLMResult, Turn
from app.schemas import (
    CreateResponseRequest,
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


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            p["text"] for p in content if isinstance(p, dict) and p.get("type") in TEXT_PARTS and "text" in p
        )
    raise APIError(400, "message content must be a string or a list of content parts", param="input")


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
            if item.get("type", "message") != "message":
                continue  # reasoning, item_reference, etc. we don't use them
            role = item.get("role")
            text = content_text(item.get("content", ""))
            if role in ("system", "developer"):
                instructions.append(text)
            elif role in ("user", "assistant"):
                turns.append(Turn(role, text))

    if not any(t.role == "user" for t in turns):
        raise APIError(400, "input must include at least one user message", param="input")
    return instructions, turns


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


def finish_response(base: ResponseResource, result: LLMResult, msg_id: str) -> ResponseResource:
    status = "incomplete" if result.truncated else "completed"
    message = OutputMessage(id=msg_id, status=status, content=[OutputText(text=result.text)])
    return base.model_copy(
        update={
            "status": status,
            "model": result.model,
            "completed_at": int(time.time()) if status == "completed" else None,
            "incomplete_details": {"reason": "max_output_tokens"} if result.truncated else None,
            "output": [message],
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

    final = finish_response(base, result, msg_id)
    message = final.output[0]
    yield event("response.output_text.done", **where, text=result.text, logprobs=[])
    yield event("response.content_part.done", **where, part=message.content[0].model_dump())
    yield event("response.output_item.done", output_index=0, item=message.model_dump())
    terminal = "response.incomplete" if final.status == "incomplete" else "response.completed"
    yield event(terminal, response=final.model_dump())
