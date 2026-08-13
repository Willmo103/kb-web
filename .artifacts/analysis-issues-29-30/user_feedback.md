# User Feedback - Issues Breakdown

The user provided design comments on the job-queue architecture:
- Define a top-level `sources` table to capture all URLs and file uploads with attributes: `id` (UUID PK), `url` (text nullable), `file_hash` (text nullable), `type` (enum source_type: `file`, `article`, `youtube_video`, `note`, `link`, `code_folder`, `git_clone_url`), `processor_id` (int nullable FK), `path` (text nullable), and `timestamp` (DateTime).
- Relate all database entities back to this `sources` table.
- Define a `_processor_xref` enum registry table in the database to register processing services (pre-processing, processing, post-processing code actions or stored procedures).
- Interaction with the queue worker is controlled via `processor_id`: each processing stage updates `processor_id` to point to the next registered processor.

This has been successfully integrated into the breakdown plan artifact.
