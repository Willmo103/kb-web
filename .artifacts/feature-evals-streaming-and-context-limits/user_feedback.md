# User Feedback Record

## Date & Session
- **Date**: 2026-10-18
- **Session**: Model Evaluation Studio Improvements & Timeout Remediation
- **Branch**: `feature/evals-streaming-and-context-limits`

## User Issues & Feedback
1. **Cloudflare Error 524 Timeout & Batch Latency**:
   - Running evaluations with multiple models (e.g. 4 models × 2 prompts × 10 rows = 80 generations) exceeds Cloudflare's 100-second proxy gateway timeout, crashing with an HTML 524 error.
   - User directive: *"New error. the session timed out. it is going to take time to load all the models. we need to just let the server cook or start using the streaming response to prevent this. I am getting tired of **fighting timeouts**!!!!!!!!!!"*

2. **Ollama Streaming & Thinking Token Capture**:
   - User directive: *"ollama client allows for streaming responses we just have to buffer them (and possibly use them to live render the content as it is created) then save the entire response once it is completed. this way we also capture thinking tokens (since I started using thinking since they all use tools during thinking now.)"*
   - Use `client.chat(..., stream=True)`, buffer tokens and thinking tokens on the server, yield SSE token chunks for live rendering in the UI, and save the complete aggregated response with thinking metadata when complete.

3. **Context Tokens Limitation**:
   - `max_tokens` was restricted by Pydantic schema validation to `le=16384`, causing HTTP 422 Unprocessable Content when setting higher token counts (e.g. 32,768).
   - User directive: *"once I set the context tokens to less than 16000 it worked, but I should be able to use as much of the models context as I want to. the chosen model has the num_ctx field in its /ps response when ollama is called. we shoul use that to determine the max allowable ctx tokens."*

4. **Frontend Alert Formatting (`[object Object]`)**:
   - When HTTP 422 errors occur, the alert displayed `Evaluation Error: [object Object]` because FastAPI's `detail` list of validation errors was stringified directly.

5. **Content Security Policy Violation**:
   - Cloudflare Web Analytics beacon script (`https://static.cloudflareinsights.com`) was blocked by Content Security Policy.

