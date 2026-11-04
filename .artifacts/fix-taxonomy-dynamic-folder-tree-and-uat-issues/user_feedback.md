# User Feedback - Taxonomy Dynamic Folder Tree & UAT Issues

## Date: 2026-11-03
## Branch: `fix/taxonomy-dynamic-folder-tree-and-uat-issues`

### Summary of Issues Reported by User:

1. **Issue 1 (Default Topics Reseeding Bug)**:
   - When all default topics were deleted and the user added their first custom topic, all default topics unexpectedly re-appeared in the topic governance list.
   - Root cause investigation needed: Find where empty topic tables trigger automatic re-seeding of hardcoded defaults (e.g. `init_default_topics`, `get_allowed_topics`, or DB migration fallback) and prevent unwanted re-seeding once a user has cleared them.

2. **Issue 2 (Inability to Edit Topics/Tags)**:
   - Once topics/nodes are added, there is no way to edit their name, description, qualification rules, or status.
   - Requirement: Add an **Edit** action to rename topics/nodes and update their metadata across the governance table, steered tree, and database items.

3. **Issue 3 (Outdated UI Text on Governance Table)**:
   - The subtitle text states topic assignment is still only for editing "2-level sub-topic taxonomies (Phylum/Class)".
   - Requirement: Update wording to describe **Taxonomy Nodes & Folders** as the immutable structural folder layer that agents must work within.

4. **Issue 4 (Folder + Button JS Error)**:
   - Clicking `+ Folder` raises `Uncaught ReferenceError: selected7TierPath is not defined at openAddFolderModal (taxonomy:2409:22)` and fails to open the modal.
   - Root cause: `selected7TierPath` variable is undefined or uninitialized in JavaScript scope. Fix variable declaration and modal opening logic.

5. **Issue 5 (Defaulting to "General" instead of "Unclassified")**:
   - Items/facts without classification are being placed under `General/General/general/general` (2,736 facts) instead of remaining **Unclassified**.
   - Requirement: Stop defaulting unclassified items to "General"; keep them unclassified until explicitly assigned or categorized.

6. **Issue 6 (Missing Search & Placement for Current Imports)**:
   - No view to search all ingested sites, articles, and pages directly within `/taxonomy` to place them into folders.
   - Requirement: Add an "Imported Items & Search" tab or panel in `/taxonomy` allowing users to search all articles/sites and easily assign/move them to any taxonomy node/folder.

7. **Issue 7 (Transition from Rigid 7-Tier Biological Design to Equal Folder Nodes)**:
   - UI still shows rigid 7-tier biological hierarchy icons (`👑 Kingdom`, `◆ Phylum`, `FAMILY`, `GENUS`, etc.).
   - Requirement: Transition all tree nodes to equal folder representations (`📁`) with metadata fields and policies (qualification questions, domain blacklists, lifecycle rules) that are inserted into decision states for each layer.

8. **Housekeeping**:
   - Ensure all post-commit changes are committed cleanly to the branch and pushed to `origin development` without lingering unstaged or uncommitted artifacts.

