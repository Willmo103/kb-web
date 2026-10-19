# User Feedback - Eval Datasets, d1 SystemOne Fix, and Central Agent Configurations

## Feedback Received
1. **Multi-Row Dataset Evaluation (not just single inputs)**:
   - Need to evaluate models on datasets with multiple rows (e.g. 20+ rows sampled from articles or custom report queries), rather than a single static input.
   - Evals data sources should be generated **exactly like reports** using custom report queries that return result rows.
   - Dedicated tab in Evals Studio to create and manage eval datasets/reports.
   - Datasets require a minimum of 20 rows to be saved as an evaluation dataset.
   - Formatting inputs via Jinja2 templates referencing `{{ data.<field> }}`:
     - LLM Prompt Template: e.g. `--- url: {{ data.url }} tags: {{ data.tags }} --- # {{ data.title }} \n\n {{ data.wiki }}`
     - Decision State Template: e.g. `{"state": {"policy": "...", "target": {{ data.target }}}}`
     - Embedding Template: e.g. `"""article: {{ data.title }} | url: {{ data.url }} | tags: {{ data.tags }} | Content: {{ data.content }}"""`
2. **Ollama / d1 / SystemOne Calling Architecture**:
   - `Client.systemone()` received an unexpected keyword argument `'options'`. Decision models do not take standard chat options (`num_predict`, `temperature`, etc.).
   - Ollama exposes `/v1/systemone` natively (and supports `typesafe-sdk`).
   - `d1` parameters: `model`, `state` (string or JSON), `questions` (map of 1-64 questions with `type` in `choice`, `noul`, `score`; `instructions`; `criteria`), optional `images`, optional `keep_alive`.
   - Returns calibrated probabilities and confidence with zero output tokens in a single forward pass.
3. **Expose Every Single Aspect of Every Ollama Call in Admin Portal**:
   - Need an exhaustive Agent/Model Configuration system exposing every parameter for every call in the codebase:
     - Model name
     - Type (`llm`, `embedding`, `decision`, `coding`)
     - System prompt template / Jinja template
     - User prompt template / Jinja template and arguments
     - Thinking mode toggle/parameters
     - Model options (where applicable: `temperature`, `num_predict`, `num_ctx`, `top_p`, `top_k`)
     - Tools (which tool primitives the agent can execute)
     - Enabled/disabled toggle
   - Expose the Log Error Agent / Error Diagnostics Agent which currently has no visibility or control.
4. **Error Handling**:
   - In Evals UI, API errors previously returned HTML error pages (e.g. 500 or 504), causing client-side `JSON.parse` alerts (`Unexpected token '<'`). Need robust JSON error envelopes and timeout/status displays.
