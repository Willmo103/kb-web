# User Intent & Disambiguation Rules

All agents operating in this repository MUST adhere to the User Intent standard at all times.

---

## 1. User Intent Primacy
- **Core Principle**: Always prioritize and fulfill the **underlying user intent**, not just the superficial or literal wording of instructions.
- Understand the real outcome the user is striving to achieve (e.g. system reliability, developer velocity, ease of agent maintenance, or performance).

## 2. Mandatory Disambiguation via Multiple Choice
- If the user's intent is **not stated**, **ambiguous**, or **otherwise unclear**:
  - The agent MUST NOT guess or make arbitrary unvalidated assumptions.
  - The agent MUST pause and solicit clarification using the `ask_question` tool (rendering an interactive multiple-choice selection to the user).
  - Structure options clearly, identifying recommended paths where technical trade-offs exist, and allow the user to select the preferred direction.
