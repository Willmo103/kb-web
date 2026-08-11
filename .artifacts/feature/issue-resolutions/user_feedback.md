# User Feedback

The user provided the following additional design feedback:

### 1. Article Card Visual Hierarchy
- **Title Size**: The article title must be the largest, most prominent element on the card (`text-base` or `text-lg font-extrabold text-gray-900`).
- **Collection Badge Size**: The collection button/badge is currently too large and dominates the card. It should be reduced to a sleek, subtle, compact badge/link (`text-[10px] px-1.5 py-0.5`).
- **Grid Columns**: Max column count should be **3** (e.g. `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5`) so cards resize themselves fluidly and have sufficient horizontal breathing room.

### 2. Admin Portal System Prompt Editor Modal
- The static prompt textareas in the Admin Dashboard are too cramped for editing large multi-paragraph system prompts.
- Implement an interactive **Prompt Editor Modal** that opens when clicking an "Edit Prompt" button or textarea, providing a spacious full-modal editor with clear Save / Cancel buttons.
