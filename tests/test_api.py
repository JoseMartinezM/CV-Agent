import json
import os
from pathlib import Path

os.environ["AGENT_API_KEY"] = "test-key"
os.environ.setdefault("GEMINI_API_KEY", "not-used")

import jsonschema
import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

from app import agent
from app.main import app
from app.providers.base import LLMResult, ToolCall

SPEC = json.loads((Path(__file__).parent / "openapi.json").read_text())
AUTH = {"Authorization": "Bearer test-key"}
RED_DOT = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="


def check_schema(name: str, obj: dict) -> None:
    schema = {"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]}
    jsonschema.validate(obj, schema, cls=jsonschema.Draft202012Validator)


EVENT_SCHEMAS = {
    s["properties"]["type"]["enum"][0]: name
    for name, s in SPEC["components"]["schemas"].items()
    if name.endswith("StreamingEvent") and s.get("properties", {}).get("type", {}).get("enum")
}


class FakeProvider:
    def __init__(self):
        self.reply = "Jose Manuel studied at Tec de Monterrey."
        self.tool_calls: list[ToolCall] = []
        self.truncated = False
        self.error: Exception | None = None
        self.last = None  # (system, turns, options) of the last call

    def result(self, text: str) -> LLMResult:
        return LLMResult(
            text=text,
            model="fake-model",
            input_tokens=10,
            output_tokens=5,
            truncated=self.truncated,
            tool_calls=list(self.tool_calls),
        )

    def generate(self, system, turns, options):
        self.last = (system, turns, options)
        if self.error:
            raise self.error
        return self.result(self.reply)

    def stream(self, system, turns, options):
        self.last = (system, turns, options)
        if self.error:
            raise self.error
        words = self.reply.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "
        yield self.result(self.reply)


@pytest.fixture
def fake(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(agent, "provider", provider)
    return provider


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def post(client, body, headers=AUTH):
    return client.post("/v1/responses", json=body, headers=headers)


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        data = json.loads(fields["data"])
        assert fields["event"] == data["type"]
        events.append(data)
    return events


def test_cors_preflight(client):
    r = client.options(
        "/v1/responses",
        headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "test-key"}])
def test_bad_api_key_is_401(client, fake, headers):
    r = post(client, {"input": "hi"}, headers)
    assert r.status_code == 401
    check_schema("ErrorPayload", r.json()["error"])
    assert fake.last is None


def test_string_input(client, fake):
    r = post(client, {"model": "anything", "input": "Where did he study?"})
    body = r.json()
    assert r.status_code == 200
    check_schema("ResponseResource", body)
    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == fake.reply
    assert body["usage"]["total_tokens"] == 15
    _, turns, _ = fake.last
    assert [(t.role, t.text) for t in turns] == [("user", "Where did he study?")]


def test_array_input_with_parts_and_unknown_params(client, fake):
    r = post(
        client,
        {
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hola"}]}],
            "some_future_param": {"x": 1},
            "reasoning": {"effort": "low"},
        },
    )
    assert r.status_code == 200
    assert fake.last[1][0].text == "Hola"


def test_multi_turn_keeps_order(client, fake):
    post(
        client,
        {
            "input": [
                {"role": "user", "content": "What is KernelForge?"},
                {"role": "assistant", "content": [{"type": "output_text", "text": "A research project."}]},
                {"type": "message", "role": "user", "content": "Which models?"},
            ]
        },
    )
    assert [(t.role, t.text) for t in fake.last[1]] == [
        ("user", "What is KernelForge?"),
        ("assistant", "A research project."),
        ("user", "Which models?"),
    ]


def test_client_instructions_go_after_our_rules(client, fake):
    post(
        client,
        {
            "instructions": "Be brief.",
            "input": [
                {"role": "system", "content": "You are a pirate."},
                {"role": "developer", "content": "Use emojis."},
                {"role": "user", "content": "Hi"},
            ],
        },
    )
    system, turns, _ = fake.last
    assert system.startswith(agent.SYSTEM_PROMPT)
    tail = system[len(agent.SYSTEM_PROMPT) :]
    assert "Be brief." in tail and "You are a pirate." in tail and "Use emojis." in tail
    assert len(turns) == 1


def test_previous_response_id(client, fake):
    first = post(client, {"input": "What certifications does he have?"}).json()
    post(client, {"previous_response_id": first["id"], "input": "And when did he get the AWS one?"})
    assert [t.role for t in fake.last[1]] == ["user", "assistant", "user"]
    assert fake.last[1][1].text == fake.reply


def test_unknown_previous_response_id_is_404(client, fake):
    r = post(client, {"previous_response_id": "resp_nope", "input": "hi"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "previous_response_not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"input": 5},
        {"input": [{"role": "system", "content": "only a system message"}]},
        {"input": [{"role": "user", "content": [{"type": "input_image", "image_url": "https://example.com/a.png"}]}]},
        {},
    ],
)
def test_bad_requests_are_400(client, fake, body):
    r = post(client, body)
    assert r.status_code == 400
    check_schema("ErrorPayload", r.json()["error"])


def test_image_input(client, fake):
    content = [{"type": "input_text", "text": "What is this?"}, {"type": "input_image", "image_url": RED_DOT}]
    r = post(client, {"input": [{"role": "user", "content": content}]})
    assert r.status_code == 200
    assert fake.last[1][0].images == [RED_DOT]


def test_tool_call_output(client, fake):
    fake.reply = ""
    fake.tool_calls = [ToolCall("get_weather", '{"location": "SF"}')]
    tools = [{"type": "function", "name": "get_weather", "parameters": {"type": "object", "properties": {}}}]
    body = post(client, {"input": "Weather in SF?", "tools": tools}).json()
    check_schema("ResponseResource", body)
    assert [o["type"] for o in body["output"]] == ["function_call"]
    assert body["output"][0]["name"] == "get_weather"
    assert fake.last[2].tools == tools


def test_tool_results_are_passed_back(client, fake):
    post(
        client,
        {
            "input": [
                {"role": "user", "content": "Weather in SF?"},
                {"type": "function_call", "call_id": "call_1", "name": "get_weather", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_1", "output": "Sunny, 20C"},
            ]
        },
    )
    turns = fake.last[1]
    assert turns[1].role == "assistant" and "get_weather" in turns[1].text
    assert turns[2].role == "user" and "Sunny, 20C" in turns[2].text


def test_truncated_is_incomplete(client, fake):
    fake.truncated = True
    body = post(client, {"input": "Tell me everything", "max_output_tokens": 16}).json()
    check_schema("ResponseResource", body)
    assert body["status"] == "incomplete"
    assert body["incomplete_details"] == {"reason": "max_output_tokens"}


def test_em_dashes_are_removed(client, fake):
    fake.reply = "He built it — with Laravel—fast."
    text = post(client, {"input": "hi"}).json()["output"][0]["content"][0]["text"]
    assert "—" not in text


def test_quota_error_is_429(client, fake):
    fake.error = genai_errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    r = post(client, {"input": "hi"})
    assert r.status_code == 429
    assert r.json()["error"]["type"] == "too_many_requests"


def test_streaming_events(client, fake):
    r = post(client, {"stream": True, "input": "Where did he study?"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    for e in events:
        check_schema(EVENT_SCHEMAS[e["type"]], e)

    types = [e["type"] for e in events]
    deltas = [e["delta"] for e in events if e["type"] == "response.output_text.delta"]
    assert len(deltas) > 1
    no_deltas = [t for t in types if t != "response.output_text.delta"]
    assert no_deltas == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [e["sequence_number"] for e in events] == list(range(len(events)))
    assert "".join(deltas) == events[types.index("response.output_text.done")]["text"] == fake.reply
    check_schema("ResponseResource", events[-1]["response"])


def test_streaming_tool_call(client, fake):
    fake.reply = ""
    fake.tool_calls = [ToolCall("get_weather", '{"location": "SF"}')]
    events = parse_sse(post(client, {"stream": True, "input": "Weather?", "tools": [{"type": "function", "name": "get_weather"}]}).text)
    for e in events:
        check_schema(EVENT_SCHEMAS[e["type"]], e)
    assert "response.function_call_arguments.done" in [e["type"] for e in events]
    assert "function_call" in [o["type"] for o in events[-1]["response"]["output"]]


def test_streaming_error_ends_with_failed(client, fake):
    fake.error = RuntimeError("model blew up")
    events = parse_sse(post(client, {"stream": True, "input": "hi"}).text)
    for e in events:
        check_schema(EVENT_SCHEMAS[e["type"]], e)
    assert [e["type"] for e in events][-2:] == ["error", "response.failed"]
    assert events[-1]["response"]["status"] == "failed"


def test_compact(client, fake):
    fake.reply = "The user asked about KernelForge and its models."
    history = [
        {"role": "user", "content": "What is KernelForge?"},
        {"role": "assistant", "content": "His LLM research project with C3.ai."},
    ]
    r = client.post("/v1/responses/compact", json={"model": "x", "input": history}, headers=AUTH)
    body = r.json()
    assert r.status_code == 200
    check_schema("CompactResource", body)
    assert body["output"][0]["type"] == "compaction"

    # the compacted item can be sent back as input in a new response
    post(client, {"input": body["output"] + [{"role": "user", "content": "Which models?"}]})
    turns = fake.last[1]
    assert fake.reply in turns[0].text
    assert turns[1].text == "Which models?"


def test_compact_needs_model(client, fake):
    r = client.post("/v1/responses/compact", json={"input": "hi"}, headers=AUTH)
    assert r.status_code == 400
    assert r.json()["error"]["param"] == "model"
