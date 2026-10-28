# Open Responses compliance

Official tester: https://www.openresponses.org/compliance (spec version 2026-04-24)
Endpoint tested: `https://cv-agent-psi.vercel.app/v1`
Date: 2026-10-27

## Result: 10/10 passed

| Test | What it checks | Result |
|---|---|---|
| Basic Text Response | Simple user message, full `ResponseResource` schema | ✅ |
| Assistant Message Phase | Assistant history with `phase` labels is accepted | ✅ |
| Response Output Phase Schema | Schema support for output phase labels | ✅ |
| Streaming Response | SSE events, order and final response | ✅ |
| System Prompt | `system` role message in `input` | ✅ |
| Tool Calling | Client function tool returns a `function_call` item | ✅ |
| Image Input | `input_image` with a base64 data URL | ✅ |
| Multi-turn Conversation | User + assistant history | ✅ |
| Compaction Endpoint | `POST /v1/responses/compact` returns a `response.compaction` | ✅ |
| Compaction Missing Required Model | Compact request without `model` is rejected (400) | ✅ |

The first run was 8/10, before `/v1/responses/compact` existed. It was added and the rerun passed everything.

## Not covered

The CLI version of the tester also has 7 WebSocket tests. They can't run from the browser and
WebSocket transport is not implemented on purpose: the Banorte platform talks over HTTP, and
long lived connections don't fit Vercel's function time limits.

## Notes from the run

- The tester sends all requests at once. Every response came from `gemini-3.5-flash-lite`,
  which means the main model (`gemini-3.5-flash`) hit the free tier rate limit and the
  automatic fallback took over without any test failing.
- The same requests are also covered by `tests/test_api.py`, which validates every response
  and every streaming event against the official OpenAPI schema (`tests/openapi.json`).

## How to reproduce

Open the tester page, set the base URL to `https://cv-agent-psi.vercel.app/v1` and use the
agent API key. Or with the CLI from the openresponses repo:

```
bun run test:compliance --base-url https://cv-agent-psi.vercel.app/v1 --api-key $AGENT_API_KEY
```
