import json
import secrets
import time

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google.genai import errors as genai_errors

from app import agent
from app.config import settings
from app.responses import APIError, build_response, new_id, normalize_input, save_history
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
    if e.code == 429:
        err = APIError(429, "The model is out of quota, try again in a minute", type="too_many_requests")
    else:
        err = APIError(500, "The model failed to answer, try again", type="model_error")
    return error_response(err)


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

    result = agent.answer(turns, instructions, req.temperature, req.max_output_tokens)
    response = build_response(req, result, response_id, int(start))
    save_history(response_id, turns, result.text)

    log(
        request_id=response_id,
        path="/v1/responses",
        stream=False,
        model=result.model,
        status=response.status,
        turns=len(turns),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=int((time.time() - start) * 1000),
    )
    return response
