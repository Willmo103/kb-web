CREATE TABLE [fetched_pages] (
   [url] TEXT PRIMARY KEY,
   [title] TEXT,
   [html_content] TEXT,
   [md_content] TEXT,
   [links] TEXT,
   [html_content_hash] TEXT,
   [md_content_hash] TEXT,
   [fetched_at] TEXT,
   [description] TEXT,
   [keywords] TEXT,
   [tags] TEXT
, [collection_id] INTEGER, [exclude_from_general] INTEGER);

CREATE TABLE [page_versions] (
   [id] INTEGER PRIMARY KEY,
   [url] TEXT,
   [title] TEXT,
   [html_content] TEXT,
   [md_content] TEXT,
   [links] TEXT,
   [html_content_hash] TEXT,
   [md_content_hash] TEXT,
   [fetched_at] TEXT,
   [description] TEXT,
   [keywords] TEXT,
   [tags] TEXT
);

CREATE TABLE [article_embeddings] (
   [url] TEXT PRIMARY KEY REFERENCES [fetched_pages]([url]),
   [embedding] TEXT,
   [updated_at] TEXT
);

CREATE TABLE [title_embeddings] (
   [url] TEXT PRIMARY KEY REFERENCES [fetched_pages]([url]),
   [embedding] TEXT,
   [updated_at] TEXT
);

CREATE TABLE [site_wikis] (
   [site] TEXT PRIMARY KEY,
   [wiki_content] TEXT,
   [updated_at] TEXT
);

CREATE TABLE [youtube_videos] (
   [url] TEXT PRIMARY KEY REFERENCES [fetched_pages]([url]),
   [video_id] TEXT,
   [creator] TEXT,
   [channel_id] TEXT,
   [duration] INTEGER,
   [view_count] INTEGER,
   [thumbnail_url] TEXT,
   [local_path] TEXT,
   [updated_at] TEXT
);

CREATE TABLE [collections] (
   [id] INTEGER PRIMARY KEY,
   [title] TEXT,
   [visibility] TEXT,
   [rag_system_prompt] TEXT,
   [taxonomy_system_prompt] TEXT,
   [general_system_context] TEXT,
   [created_at] TEXT
);

CREATE TABLE [collection_items] (
   [id] INTEGER PRIMARY KEY,
   [collection_id] INTEGER REFERENCES [collections]([id]),
   [source_type] TEXT,
   [source_id] TEXT,
   [item_note] TEXT,
   [taxonomy_path] TEXT,
   [item_order] INTEGER,
   [added_at] TEXT
);

CREATE UNIQUE INDEX [idx_collection_items_collection_id_source_type_source_id]
    ON [collection_items] ([collection_id], [source_type], [source_id]);

CREATE TABLE [collection_notes] (
   [id] INTEGER PRIMARY KEY,
   [collection_id] INTEGER REFERENCES [collections]([id]),
   [title] TEXT,
   [content] TEXT,
   [taxonomy_path] TEXT,
   [created_at] TEXT,
   [updated_at] TEXT
);

CREATE INDEX [idx_collection_notes_collection_id]
    ON [collection_notes] ([collection_id]);

CREATE TABLE [chunk_embeddings] (
   [id] INTEGER PRIMARY KEY,
   [source_type] TEXT,
   [source_id] TEXT,
   [source_title] TEXT,
   [chunk_number] INTEGER,
   [chunk_content] TEXT,
   [chunk_vector] TEXT,
   [created_at] TEXT
);

CREATE INDEX [idx_chunk_embeddings_source_type_source_id_chunk_number]
    ON [chunk_embeddings] ([source_type], [source_id], [chunk_number]);

CREATE TABLE [video_embeddings] (
   [url] TEXT PRIMARY KEY REFERENCES [fetched_pages]([url]),
   [embedding] TEXT,
   [updated_at] TEXT
);

CREATE TABLE [ollama_logs] (
   [id] INTEGER PRIMARY KEY,
   [timestamp] TEXT,
   [model] TEXT,
   [prompt_type] TEXT,
   [messages] TEXT,
   [options] TEXT,
   [response] TEXT,
   [duration] FLOAT,
   [status] TEXT
);

CREATE TABLE [settings_ollama] (
   [key] TEXT PRIMARY KEY,
   [value] TEXT
);

CREATE TABLE [settings_external] (
   [key] TEXT PRIMARY KEY,
   [value] TEXT
);

CREATE TABLE [agent_prompts] (
   [id] INTEGER PRIMARY KEY,
   [prompt_type] TEXT,
   [prompt_text] TEXT,
   [is_head] INTEGER,
   [created_at] TEXT,
   [version] INTEGER
);

CREATE TABLE [cli_api_keys] (
   [key] TEXT PRIMARY KEY,
   [name] TEXT,
   [created_at] TEXT
);

CREATE TABLE [registered_clients] (
   [computer_name] TEXT PRIMARY KEY,
   [api_key] TEXT,
   [registered_at] TEXT,
   [status] TEXT
);

CREATE TABLE [links] (
   [id] INTEGER PRIMARY KEY,
   [url] TEXT,
   [title] TEXT,
   [description] TEXT,
   [click_count] INTEGER,
   [created_at] TEXT,
   [last_clicked_at] TEXT
);

CREATE UNIQUE INDEX [idx_links_url]
    ON [links] ([url]);
