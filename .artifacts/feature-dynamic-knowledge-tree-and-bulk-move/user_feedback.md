# User Feedback: Dynamic Knowledge Tree / Folder Graph, Direct Topic Deletion & Bulk Item/Fact Relocation

**Date**: 2026-11-02  
**Branch**: `feature/dynamic-knowledge-tree-and-bulk-move`  

## User Feedback & Requirements

The user provided a live screenshot from `https://kb-test.willmo.dev/taxonomy` showing the current Topic & Sub-Topic Governance interface prompting to "Deny & Requeue" an unwanted sub-topic (`software developer/portfolio`), with items trapped in rigid structures.

The user outlined the following core requirements:
1. **Dynamic Topic & Sub-Topic Management**:
   - The `/taxonomy` screen needs to be far more dynamic.
   - The user must be able to **directly DELETE topics and sub-topics** (permanently deleting them and cleaning up associations, rather than merely toggling them to `[DENIED]`).
2. **File-Tree / Folder Knowledge Graph**:
   - The system should function **like a flexible file tree / folder hierarchy** rather than an artificial, rigid 7-tier biological taxonomy.
   - The user can build and structure as much of the tree as they want (adding root folders, nested sub-folders, custom layers to arbitrary depths).
   - Agents can choose appropriate layers/folders anywhere in this tree when classifying content.
   - Articles, notes, and videos can reside at any level in the hierarchy if it makes sense there.
3. **Bulk Relocation & Re-parenting for Items and Facts**:
   - The user must be able to move whatever items the agents place into any folder.
   - Ability to move large quantities of files (articles, notes, videos) and atomic context facts from one folder/layer to another in bulk (or move an entire branch/family).
   - Moving items must update their taxonomic coordinates, page topics, entity records, and fact canonical paths cleanly in the database.
4. **Unified Information + Personal Contextual Layer**:
   - The knowledge tree should serve as both the information organization structure AND the user's subjective contextual/value layer.

