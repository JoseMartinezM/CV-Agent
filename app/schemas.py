# only the parts of the Open Responses spec we actually use.
# field names taken from public/openapi/openapi.json, spec version 2026-04-24

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Status = Literal["queued", "in_progress", "completed", "failed", "incomplete"]
ItemStatus = Literal["in_progress", "completed", "incomplete"]


class CreateResponseRequest(BaseModel):
    # the spec has many more optional fields (reasoning, include, store...).
    # we accept them and just ignore what we don't use
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    # items can be messages, function_call_output, item_reference, etc.
    # they get normalized in responses.py, so keep them loose here
    input: str | list[dict[str, Any]] | None = None
    instructions: str | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    previous_response_id: str | None = None
    metadata: dict[str, Any] | None = None


class OutputText(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[Any] = []


class OutputMessage(BaseModel):
    type: Literal["message"] = "message"
    id: str
    status: ItemStatus = "completed"
    role: Literal["assistant"] = "assistant"
    content: list[OutputText]


class FunctionCall(BaseModel):
    type: Literal["function_call"] = "function_call"
    id: str
    call_id: str
    name: str
    arguments: str  # json string, not an object
    status: ItemStatus = "completed"


class InputTokensDetails(BaseModel):
    cached_tokens: int = 0


class OutputTokensDetails(BaseModel):
    reasoning_tokens: int = 0


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_tokens_details: InputTokensDetails = InputTokensDetails()
    output_tokens_details: OutputTokensDetails = OutputTokensDetails()


class ResponseError(BaseModel):
    code: str
    message: str


class ResponseResource(BaseModel):
    # every field here is "required" in the spec, even the ones that are always null for us
    id: str
    object: Literal["response"] = "response"
    created_at: int
    completed_at: int | None = None
    status: Status
    incomplete_details: dict[str, str] | None = None
    model: str
    previous_response_id: str | None = None
    instructions: str | None = None
    output: list[OutputMessage | FunctionCall] = []
    error: ResponseError | None = None
    tools: list[dict[str, Any]] = []
    tool_choice: str | dict[str, Any] = "auto"
    truncation: Literal["auto", "disabled"] = "disabled"
    parallel_tool_calls: bool = True
    text: dict[str, Any] = {"format": {"type": "text"}}
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    top_logprobs: int = 0
    temperature: float = 1.0
    reasoning: dict[str, Any] | None = None
    usage: Usage | None = None
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    store: bool = False
    background: bool = False
    service_tier: str = "default"
    metadata: dict[str, Any] = {}
    safety_identifier: str | None = None
    prompt_cache_key: str | None = None


class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
