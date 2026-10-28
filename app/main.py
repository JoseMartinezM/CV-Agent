import json
import secrets
import time
from collections.abc import Callable, Iterator

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from google.genai import errors as genai_errors

from app import agent
from app.config import settings
from app.providers.base import LLMResult, Turn
from app.responses import (
    APIError,
    as_api_error,
    base_response,
    finish_response,
    new_id,
    normalize_input,
    options_from,
    save_history,
    stream_events,
)
from app.schemas import CreateResponseRequest, ErrorDetail, ErrorResponse, ResponseResource

app = FastAPI(title="Jose Manuel CV Agent")


def log(severity: str = "INFO", **fields) -> None:
    # one json line per event, cloud logging picks up "severity" on its own
    print(json.dumps({"severity": severity, **fields}, ensure_ascii=False), flush=True)


def error_response(e: APIError) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(message=e.message, type=e.type, code=e.code, param=e.param))
    return JSONResponse(status_code=e.status, content=body.model_dump())


@app.exception_handler(APIError)
def handle_api_error(request: Request, e: APIError):
    log("WARNING", path=request.url.path, status=e.status, error=e.message)
    return error_response(e)


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, e: RequestValidationError):
    first = e.errors()[0]
    loc = [str(x) for x in first["loc"] if x != "body"]
    param = loc[0] if loc else None
    return handle_api_error(request, APIError(400, first["msg"], param=param))


@app.exception_handler(genai_errors.APIError)
def handle_model_error(request: Request, e: genai_errors.APIError):
    log("ERROR", path=request.url.path, model_status=e.code, error=str(e)[:500])
    return error_response(as_api_error(e))


@app.exception_handler(Exception)
def handle_unexpected(request: Request, e: Exception):
    log("ERROR", path=request.url.path, error=repr(e)[:500])
    return error_response(APIError(500, "Internal server error", type="server_error"))


def check_api_key(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {settings.agent_api_key}"
    if not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise APIError(401, "Invalid or missing API key", type="invalid_request_error", code="invalid_api_key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/responses", dependencies=[Depends(check_api_key)], response_model=ResponseResource)
def create_response(req: CreateResponseRequest):
    start = time.time()
    response_id = new_id("resp")
    instructions, turns = normalize_input(req)

    def done(result: LLMResult, status: str) -> None:
        save_history(response_id, turns, result.text)
        log(
            request_id=response_id,
            path="/v1/responses",
            stream=req.stream,
            model=result.model,
            status=status,
            turns=len(turns),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            tool_calls=len(result.tool_calls),
            latency_ms=int((time.time() - start) * 1000),
        )

    if req.stream:
        return StreamingResponse(
            stream_with_logging(req, response_id, int(start), instructions, turns, done),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    result = agent.answer(turns, instructions, options_from(req))
    response = finish_response(base_response(req, response_id, int(start), result.model), result, new_id("msg"))
    done(result, response.status)
    return response


def stream_with_logging(
    req: CreateResponseRequest,
    response_id: str,
    created_at: int,
    instructions: list[str],
    turns: list[Turn],
    done: Callable[[LLMResult, str], None],
) -> Iterator[str]:
    def chunks():
        try:
            for item in agent.answer_stream(turns, instructions, options_from(req)):
                if isinstance(item, LLMResult):
                    done(item, "incomplete" if item.truncated else "completed")
                yield item
        except Exception as e:
            log("ERROR", request_id=response_id, path="/v1/responses", stream=True, error=repr(e)[:500])
            raise

    yield from stream_events(req, response_id, created_at, settings.llm_model, chunks())
