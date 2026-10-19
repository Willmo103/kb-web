# Implementation Plan: SSE Streaming Evaluations, Dynamic Model Context Discovery, and CSP Fixes

**Branch**: `feature/evals-streaming-and-context-limits`  
**Target Baseline**: `development`  
**Artifact Directory**: `.artifacts/feature-evals-streaming-and-context-limits/`

---

## 1. Objectives & Scope

1. **Neutralize Cloudflare 524 Timeouts via Real-Time Server-Sent Events (SSE) & Live Token Streaming**:
   - Provide persistent streaming responses (`POST /api/evals/matrix/stream`) using `StreamingResponse(..., media_type="text/event-stream")`.
   - Call Ollama with `client.chat(..., stream=True)` in a thread worker / generator.
   - Buffer delta tokens on the backend while simultaneously yielding `event: token` SSE chunks for live character-by-character rendering.
   - **Thinking Tokens & Reasoning Traces**: Capture `thinking` tokens emitted by thinking models (e.g. `gemma4`, `qwen3.5`, `deepseek`) or `<think>...</think>` tags. Stream them separately as `thinking` deltas and save them in the final evaluation record.
   - Send immediate initial headers/handshake (`event: start`) within <100ms so Cloudflare proxy receives bytes immediately, and emit heartbeats (`: keep-alive\n\n`) during model initialization.
   - When each run completes, yield `event: item` with the complete buffered response, thinking block, metrics, and latency.
   - In the frontend UI, live-render incoming text and collapsible thinking blocks into real-time cards with a live progress bar.


2. **Dynamic Model Context Window Discovery & Uncapped `max_tokens`**:
   - Query Ollama `GET /api/ps` to read runtime loaded models and their active `context_length` / `num_ctx`.
   - Query Ollama `POST /api/show` to extract native model context architectures (e.g. `gemma4.context_length: 131072`, `granite: 32768`).
   - Remove the hardcoded `le=16384` limit from `MatrixRunRequest.max_tokens` (increase limit to `le=262144` or model context limit).
   - Ensure Ollama `chat` options include `num_ctx = max(4096, payload.max_tokens)` so Ollama does not truncate prompts to its default 2048 tokens.
   - Expose `GET /api/evals/models/info` so the UI displays model context limits and dynamically updates maximum token inputs.

3. **Clean Frontend Error Formatting (Eliminate `[object Object]` & Raw HTML alerts)**:
   - Standardize error response parsing in `evals.j2.html` with a helper `formatApiError()`.
   - Parse FastAPI 422 validation error arrays (`loc`, `msg`) into clean readable text.
   - Extract `<title>` or clean summary if an upstream gateway (e.g. Cloudflare) returns an HTML error page.

4. **Content Security Policy (CSP) Cloudflare Insights Whitelist**:
   - Whitelist `https://static.cloudflareinsights.com` in `script-src` and `https://cloudflareinsights.com` in `connect-src` in `src/kb_web/server.py`.

---

## 2. Proposed Changes & Architecture

### Backend:
- **`src/kb_web/routers/evals.py`**:
  - Update `MatrixRunRequest` and `DecisionRunRequest` to allow `max_tokens` and `context_window` up to 262,144.
  - Implement `_get_model_context_metadata(client)` helper that queries `ps()` and `show()` to map models to their true context limits.
  - Add `GET /api/evals/models/info` endpoint returning model context and loaded VRAM status.
  - Add `POST /api/evals/matrix/stream` endpoint returning `StreamingResponse` yielding SSE events:
    - `event: start` -> total runs count, models, prompts.
    - `event: ping` -> keep-alive heartbeat while model is loading/generating.
    - `event: item` -> each completed evaluation result object.
    - `event: done` -> overall completion summary.
  - Update options in Ollama calls to pass `num_ctx` alongside `num_predict`.

- **`src/kb_web/server.py`**:
  - Add `https://static.cloudflareinsights.com` to `script-src` and `https://cloudflareinsights.com` to `connect-src` in `_inject_security_headers()`.

### Frontend:
- **`src/kb_web/templates/evals.j2.html`**:
  - Update `executeMatrixEval()` to use `fetch()` with reader stream parsing on `/api/evals/matrix/stream`.
  - Add live progress bar above the results grid showing current run progress (`X of Y completed`).
  - Render cards dynamically as events arrive rather than waiting for the entire batch to finish.
  - Add `formatApiError()` helper to format 422 JSON validation errors and HTML proxy errors into clean human-readable text.
  - Fetch model info on load to display context badges and update `matrixMaxTokens` limits.

---

## 3. Verification & Testing

1. **Unit Tests**:
   - Create `tests/test_evals_streaming_and_context.py` verifying:
     - `GET /api/evals/models/info` returns valid context metadata.
     - `POST /api/evals/matrix/stream` yields proper SSE event format (`start`, `item`, `done`).
     - Validation accepts `max_tokens` up to 131,072.
     - CSP headers include Cloudflare Insights domains.
2. **Template Verification**:
   - Run `verify_ui_templates.py`.
3. **Live Server Deployment & Browser Testing**:
   - Deploy to `websrvr` (`kb-test.service`).
   - Run a multi-model matrix test in the browser to confirm streaming results appear incrementally without Cloudflare 524 timeouts.
