# User Feedback - Turn 2026-09-13T19:20:02-05:00

## User Request
> "Next feature I want to add is an option to crawl a webpage, but I want to crawl the URLs possible fisrt and use a radio selection to choose the URLS that are actually added to the scraping queue.
> 
> Additionally I could have AI pre-check the form data using a button and presenting the agent with a tool call or structutred format or something"

## Requirements Breakdown & Analysis
1. **URL Discovery / Crawl Exploration**:
   - Given a seed webpage URL, discover and extract internal hyperlinks without immediately scraping/processing them all.
   - Return clean candidate URLs along with their anchor titles and contextual metadata.
   - Strip hash fragments, query trackers, and invalid schemes (`mailto:`, `javascript:`).
   - Check database to indicate whether candidate links are already in the knowledge base.

2. **Interactive Selection Interface**:
   - Provide a modern, intuitive preview UI with selection controls (radios/checkboxes) allowing the user to review all candidate links discovered.
   - Support Select All, Deselect All, Select New Only, and real-time search filtering across candidate links.

3. **AI Pre-Checking with Custom Instructions & Language / Noise Filtering**:
   - Priority in system prompt: Prioritize core documentation, tutorials, technical guides, and substantive content.
   - Strict exclusions in system prompt:
     - Exclude links in other languages (e.g. `/zh/`, `/ja/`, `/es/`, `/fr/` or language pickers).
     - Exclude sitemaps, RSS/Atom feeds, XML files.
     - Exclude boilerplate/utility links: login, signup, terms of service, privacy policy, legal disclaimers.
     - Exclude social sharing and root profile links.
   - Optional UI input: "Custom AI Curation Instructions (Optional)" allowing user-supplied driving prompts (e.g. *"focus on API reference"* or *"only select blog posts about transformers"*).
   - Structured JSON output format (`format="json"`) from Ollama returning selected URLs and curation reasoning.

4. **Background Scraping Queue & Site Notifications**:
   - Background batch processing so the user can continue browsing without UI blocking.
   - Clear site flash/toast notification upon enqueueing, plus Gotify alerts on completion.
