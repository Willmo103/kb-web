# User Feedback

## Turn Metadata
- **Date/Time**: 2026-10-13T18:38:31-05:00
- **Branch**: `fix/import-page-config-undefined` (branched off `development`)

## User Input
```text
Proceed and mark these as future issues: 

second: I want the error agent to be able to view the sourcecode through tools and have a system message that explains the codebase and gives a distilled version of the docs usefull for debugging the live process. I don't want it to make changes, but maybe create issues on the repo. IDK what that would require as far as credentialing but whatever it takes it should be explained and made available in the system message. 

---
This issue should be created on the repo and not acted on just yet: a __future__ issue.
Issue: Expose various system messages in the admin portal
In a recent issue all of the hardcoded values across the project were brought to the admin portal to expose the values to alow for live reconfiguration. This DID NOT capture all of the hardcoded values. it only captured the NUMERICAL values. ALLL of the hardcoded system message and prompt template strings that are parts of the configuration need to be added to the admin portal. The admin portal needs to be refactored to layout the various prompts available to edit iin a better way than a prefilled text area; maybe a tab and a monoco editor. (all prompts and system messages should have markdown hilighting. Ideally if it live rendered the markdown as written like obsidian) 
```

## Action Items
1. **Immediate Task**:
   - Apply the defense-in-depth fix for `'config' is undefined` on `GET /import`.
   - Run tests (`uv run pytest`) and verify.
   - Update `CHANGELOG.md`.
   - Merge fix into `development` and push `development` and `production` to remote origin.
2. **Future Issues to Create on GitHub Repository**:
   - Issue A: Error Agent: Source code inspection tools, distilled docs in system message, and read-only issue reporting capability.
   - Issue B: Expose system messages and prompts in the Admin Portal with Monaco editor and live Markdown preview.
