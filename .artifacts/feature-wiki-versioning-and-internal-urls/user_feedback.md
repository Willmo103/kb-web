# User Feedback: Wiki Versioning & Internal URL Scheme Routing

## User Input (Turn 1)
- **Date**: 2026-10-21
- **Prompt**:
  > "i want to be able to store versions of wikis like I do when I refetch a page; when I regenreate a wiki I want a version of that. They can be deleted on CASCADE when the base content is deleted. 
  > ---
  > For the URLS like note://... I really wish they whould either be disabled or route you to the content page Notes: note page in notes tab. workspace: open the workspace... etc. I just hate clickable links that go nowhere."
- **Additional Instruction**:
  > "when complete commit to development"

## Core Requirements & Design Analysis

### 1. Wiki Versioning Architecture
- **Version Storage on Regeneration**:
  - When a wiki is regenerated (via `/admin/regenerate/wiki`, CLI `/update/wiki`, or worker processes), the current wiki entry in `FetchedPage.description` must be preserved in a version history table before the new content is written.
  - Dedicated `WikiVersion` table in `models_orm.py` with foreign key `ForeignKey("fetched_pages.url", ondelete="CASCADE")`, capturing `url`, `title`, `wiki_content`, `model_name`, and `created_at`.
- **Cascade Deletion**:
  - When the parent `FetchedPage` is deleted (via `/admin/delete/page`, REST API batch delete, or note deletion), all corresponding `WikiVersion` records are deleted automatically via DB-level foreign key CASCADE and explicit session deletion.
- **UI Inspection & Restoration**:
  - Provide a Wiki Version selector on `/view/page` allowing users to view past iterations of generated wikis, inspect generation timestamps, and optionally restore a previous version.

### 2. Internal / Synthetic Scheme URL Routing (`note://`, `workspace://`)
- **Root Problem**:
  - Synthetic URLs (`note://vault/folder/slug`, `workspace://{id}/snapshot/{tag}`) are currently rendered as `<a href="{{ page.url }}" target="_blank">` or in markdown links. In browsers without custom OS handler registration, clicking these links does nothing or produces a protocol error.
- **Content Page Routing**:
  - `note://...`: Route to the Notes tab Monaco Editor (`/notes/edit?url=...` or `/notes/editor?url=...`).
  - `workspace://{workspace_id}/...`: Parse the workspace ID and route to `/workspaces/{workspace_id}`.
- **Link Safety & Disabling**:
  - Any non-HTTP/HTTPS and non-internal pseudo schemes must not be rendered as blind target="_blank" links.
  - Provide a backend redirect/dispatch route (`GET /open?url=...`) and a global client-side link interceptor in `base.j2.html` so internal links in rendered Markdown or summaries route properly.
  - In template cards and headers, replace dead external links with styled routing action badges ("📝 Open in Notes", "💻 Open in Workspace").

### 3. Release & Branch Delivery
- Branch: `feature/wiki-versioning-and-internal-urls` off latest `development`.
- Gated Pre-commit verification: `uv run pytest` and `uv run python build.py`.
- Final delivery: Commit and push / merge into `development`.

---

## User Input (Turn 2)
- **Date**: 2026-10-22
- **Prompt**:
  > "go"
- **Status**: Implementation plan confirmed. Proceeding with execution of Phase 1 through 5.

---

## User Input (Turn 3)
- **Date**: 2026-10-22
- **Prompt**:
  > "Sorry I forgot a major addition to this; I want to be able to choose a new model on-the-fly in the regenerate-wiki page and add additional steering instructions in a little modal form. I also want the model that generated that version recorded and displayed on the page."
- **Scope & Requirements**:
  1. **On-the-fly Model Selection**: Provide an interactive modal dialog when triggering "🔄 Regenerate Wiki" allowing the user to choose an Ollama completion model from installed models (pre-selected to the current active model).
  2. **Custom Steering Instructions**: Include an optional multi-line text input in the modal for steering instructions (e.g. "Focus on architecture diagrams", "Format as concise bullet points").
  3. **Generating Model Attribution**: Record `model_name` and `steering_instructions` on each `WikiVersion` and `wiki_model` on `FetchedPage`. Display the generating model and timestamp on `/view/page` and across the version selector.

