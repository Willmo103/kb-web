"""Tests for CLI API auth/actions, Browser Extension HTML import, and Obsidian Vault CLI Sync."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from kb_web.base import config, db_session
from kb_web.models_orm import CliApiKey, FetchedPage, WikiVersion
from kb_web.server import app

# Make kb_web_cli importable for testing
CLI_SRC = Path(__file__).resolve().parent.parent / "kb-web-cli" / "src"
if str(CLI_SRC) not in sys.path:
    sys.path.insert(0, str(CLI_SRC))

from typer.testing import CliRunner  # noqa: E402
from kb_web_cli.main import app as cli_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_cli_ext_test_data(monkeypatch):
    orig_vault = config.obsidian_vault_path
    orig_src = config.obsidian_sources_subpath
    orig_art = config.obsidian_articles_subpath
    monkeypatch.setattr(type(config), "allow_insecure_defaults", property(lambda self: True))
    yield
    config.obsidian_vault_path = orig_vault
    config.obsidian_sources_subpath = orig_src
    config.obsidian_articles_subpath = orig_art

    urls = [
        "https://ext-test.example.com/hello-world",
        "https://cli-sync-test.example.com/docs/intro",
    ]
    with db_session() as session:
        session.query(WikiVersion).filter(WikiVersion.url.in_(urls)).delete(
            synchronize_session=False
        )
        session.query(FetchedPage).filter(FetchedPage.url.in_(urls)).delete(
            synchronize_session=False
        )
        session.query(CliApiKey).filter(CliApiKey.key == "cli-test-key-xyz").delete(
            synchronize_session=False
        )
        session.commit()


def test_browser_extension_html_import_with_api_key(client):
    """Simulates Chrome browser extension POSTing active tab HTML with X-API-Key."""
    with db_session() as session:
        session.add(CliApiKey(key="cli-test-key-xyz", name="Ext Test Key"))
        session.commit()

    payload = {
        "url": "https://ext-test.example.com/hello-world",
        "title": "Extension Test Page",
        "html_content": "<html><head><title>Extension Test Page</title></head><body><article><h1>Hello</h1><p>Extension body content for testing ingestion.</p></article></body></html>",
    }

    with patch("kb_web.routers.api.extract_wiki_content", return_value="# Extension Test Page\n\nWiki digest."), patch(
        "kb_web.routers.api.extract_tags_content", return_value=["extension", "test"]
    ), patch("kb_web.routers.api.update_article_embedding"), patch(
        "kb_web.routers.api.generate_gemma_embeddings_for_page"
    ), patch("kb_web.routers.api.post_to_gotify"):
        res = client.post(
            "/api/import/html",
            headers={"X-API-Key": "cli-test-key-xyz"},
            json=payload,
        )

    assert res.status_code == 200
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=payload["url"]).first()
        assert page is not None
        assert "Extension body content" in (page.md_content or "")


def test_cli_api_auth_accepts_master_and_cli_keys_and_obsidian_config(client):
    """Verifies CLI endpoints accept master API key and update Obsidian config on server."""
    master_key = config.api_key
    assert master_key

    # 1. Register client with master API key (previously failed with 403)
    reg_res = client.post(
        "/api/cli/register",
        headers={"X-API-Key": master_key},
        json={"computer_name": "test-workstation"},
    )
    assert reg_res.status_code == 200
    assert reg_res.json()["status"] == "success"

    # 2. Update Obsidian vault config on server
    upd_res = client.post(
        "/api/cli/obsidian/config",
        headers={"X-API-Key": master_key},
        json={
            "vault_path": "/tmp/my-vault",
            "sources_subpath": "custom_sources",
            "articles_subpath": "kb/articles",
        },
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["sources_subpath"] == "custom_sources"
    assert upd_res.json()["articles_subpath"] == "kb/articles"

    # 3. Verify GET returns updated server config
    get_res = client.get("/api/cli/obsidian/config", headers={"X-API-Key": master_key})
    assert get_res.status_code == 200
    assert get_res.json()["vault_path"] == "/tmp/my-vault"


def test_cli_obsidian_config_and_sync_end_to_end(client, tmp_path):
    """Tests `kb-cli obsidian config` and `kb-cli obsidian sync` unpacking & diffing."""
    master_key = config.api_key
    vault_dir = tmp_path / "ObsidianVault"
    vault_dir.mkdir()
    user_note = vault_dir / "My Personal Note.md"
    user_note.write_text("# Personal Note\nDo not touch!", encoding="utf-8")

    # Seed an article in DB
    url = "https://cli-sync-test.example.com/docs/intro"
    with db_session() as session:
        session.add(
            FetchedPage(
                url=url,
                title="CLI Sync Guide",
                md_content="Raw CLI sync source markdown.",
                fetched_at="2026-11-17T10:00:00Z",
                tags=json.dumps(["cli", "obsidian"]),
            )
        )
        session.add(
            WikiVersion(
                url=url,
                title="CLI Sync Guide",
                wiki_content="Clean wiki body for CLI sync.",
                model_name="gemma4:latest",
                created_at="2026-11-17T10:01:00Z",
            )
        )
        session.commit()

    # Fake httpx.Client forwarding requests to FastAPI TestClient
    class BridgingHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def _strip_host(self, full_url: str) -> str:
            return full_url.replace("http://testserver", "")

        def get(self, full_url: str, **kwargs):
            return client.get(self._strip_host(full_url), headers=kwargs.get("headers"))

        def post(self, full_url: str, **kwargs):
            return client.post(
                self._strip_host(full_url),
                headers=kwargs.get("headers"),
                json=kwargs.get("json"),
                data=kwargs.get("data"),
            )

    cfg_file = tmp_path / "cli-config.json"
    cfg_file.write_text(
        json.dumps({"server_url": "http://testserver", "api_key": master_key}),
        encoding="utf-8",
    )

    runner = CliRunner()
    with patch("kb_web_cli.main.httpx.Client", BridgingHttpxClient), patch(
        "kb_web_cli.main.Path.home", return_value=tmp_path
    ), patch(
        "kb_web_cli.main.load_client_config",
        side_effect=lambda: json.loads(cfg_file.read_text(encoding="utf-8")),
    ), patch(
        "kb_web_cli.main.save_client_config",
        side_effect=lambda d: cfg_file.write_text(json.dumps(d), encoding="utf-8"),
    ):
        # 1. Configure vault & custom paths via CLI
        res_cfg = runner.invoke(
            cli_app,
            [
                "obsidian",
                "config",
                "--vault",
                str(vault_dir),
                "--sources-dir",
                "_raw_sources",
                "--articles-dir",
                "reference/wiki_articles",
            ],
        )
        assert res_cfg.exit_code == 0, res_cfg.output
        assert config.obsidian_sources_subpath == "_raw_sources"
        assert config.obsidian_articles_subpath == "reference/wiki_articles"

        # 2. First sync -> files added
        res_sync1 = runner.invoke(cli_app, ["obsidian", "sync"])
        assert res_sync1.exit_code == 0, res_sync1.output
        assert "Added:" in res_sync1.output

        src_file = vault_dir / "_raw_sources" / "cli-sync-test.example.com" / "docs.intro.md"
        art_file = (
            vault_dir
            / "reference"
            / "wiki_articles"
            / "Uncategorized"
            / "cli-sync-test.example.com"
            / "CLI Sync Guide.md"
        )
        assert src_file.exists()
        assert art_file.exists()
        assert "(/_raw_sources/cli-sync-test.example.com/docs.intro.md)" in art_file.read_text(encoding="utf-8")
        # User's unrelated note is untouched
        assert user_note.read_text(encoding="utf-8") == "# Personal Note\nDo not touch!"

        # 3. Second sync -> unchanged
        res_sync2 = runner.invoke(cli_app, ["obsidian", "sync"])
        assert res_sync2.exit_code == 0, res_sync2.output
        assert "Added:     0" in res_sync2.output
        assert "Updated:   0" in res_sync2.output
