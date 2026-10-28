import time
import uuid
from typing import Any

from app.providers.base import LLMResult, Turn
from app.schemas import (
    CreateResponseRequest,
    OutputMessage,
    OutputText,
    OutputTokensDetails,
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


def build_response(req: CreateResponseRequest, result: LLMResult, response_id: str, created_at: int) -> ResponseResource:
    status = "incomplete" if result.truncated else "completed"
    return ResponseResource(
        id=response_id,
        created_at=created_at,
        completed_at=int(time.time()) if status == "completed" else None,
        status=status,
        incomplete_details={"reason": "max_output_tokens"} if result.truncated else None,
        model=result.model,
        previous_response_id=req.previous_response_id,
        instructions=req.instructions,
        output=[OutputMessage(id=new_id("msg"), status=status, content=[OutputText(text=result.text)])],
        tools=[{"description": None, "parameters": None, "strict": True, **t} for t in req.tools or []],
        tool_choice=req.tool_choice or "auto",
        temperature=req.temperature if req.temperature is not None else 1.0,
        top_p=req.top_p if req.top_p is not None else 1.0,
        max_output_tokens=req.max_output_tokens,
        usage=Usage(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.input_tokens + result.output_tokens,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=result.reasoning_tokens),
        ),
        store=True,
        metadata=req.metadata or {},
    )
