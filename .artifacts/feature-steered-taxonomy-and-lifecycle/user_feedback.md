# User Feedback: Steered Taxonomy Tree, Gating Questions, Lifecycle Automation & Personal VK Layer

**Date**: 2026-11-02  
**Branch**: `feature/steered-taxonomy-and-lifecycle`  

## User Feedback & Requirements Summary

The user identified critical behavioral and architectural issues with the current LLM classification in `src/kb_web/taxonomy/engine.py`:
1. **Unconstrained Classification Issue**: Currently, the LLM has too much freedom to invent arbitrary category/taxonomy values irrespective of the actual structured tree being built.
2. **Layer-by-Layer Decision Gating**:
   - The classification process must proceed strictly layer-by-layer.
   - At each layer, a decision/choice model is presented with all valid top-level choices (or valid child choices under the selected parent).
   - Once a choice is selected, only its direct children are passed down to the subsequent layer.
   - The system must rely strictly on user steering rather than ungrounded LLM hallucination.
3. **User-Curated Frozen Structure**:
   - The user must be able to define their own root/branch structure to start.
   - That structure can be marked as **frozen**.
   - All incoming content MUST route down through the frozen structure and only attach to children at the bottom of the user's defined structure.
4. **Per-Node Gating Questions**:
   - Support adding specific gating questions/criteria for each node in the tree that the decision model evaluates before placing items into that node.
5. **Per-Node & Per-Level Blacklisting**:
   - Support blacklisting specific websites, domains, or content sources from being assigned to any specific level or node.
6. **Content Lifecycle Controls per Level/Node**:
   - **Auto-Freeze**: Content classified into designated levels/nodes automatically becomes frozen (`is_frozen = 1`).
   - **Auto-Refetch + Gotify Notification**: Content classified into other designated levels/nodes automatically re-fetches on a configurable schedule/interval, sending Gotify push alerts upon re-fetch.
7. **Complete Taxonomy Reset ("Nuke")**:
   - Provide a clean administrative action / endpoint to completely wipe and nuke all taxonomy entries, coordinates, and entity assignments across all items, allowing a fresh start with a user-steered tree.
8. **Granular Background Worker Pause ("Core Only" Mode)**:
   - Provide the ability to pause all background worker processes simultaneously (topic assignment, fact extraction, crawling, etc.) EXCEPT the core features: **AI wiki generation** and **tagging**, which are working well and must remain active.
9. **Personal VK (Value-Knowledge) Context Layer**:
   - Provide a way for the user to curate a nested JSON of personal VK (value/key-value) pairs representing personal interests, values, and core principles.
   - This nested personal VK structure will act as an additional frozen context layer injected into agent prompts and classification engines.

