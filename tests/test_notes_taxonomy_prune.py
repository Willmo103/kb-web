"""
Unit tests for taxonomy folder pruning when notes are deleted.
Verifies bottom-up pruning of empty categories and retention of categories with remaining items or children.
"""

from datetime import datetime
import json
import time
import pytest
from starlette.testclient import TestClient

from kb_web.server import app
from kb_web.base import db_session, COOKIE_NAME, generate_session_token
from kb_web.models_orm import Note, TaxonomyCategory, TaxonomyItem


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def _unique_slug(session, prefix: str) -> str:
    slug = f"{prefix}-{int(time.time() * 1000)}"
    return slug


def test_prune_empty_leaf_category_on_single_note_delete(client: TestClient):
    """When a note is deleted and its category contains no other items or subcategories, the category is pruned."""
    now_str = datetime.now().isoformat()
    with db_session() as session:
        cat = TaxonomyCategory(
            name="Orphan Leaf Category",
            slug=_unique_slug(session, "orphan-leaf"),
            item_count=1,
            doc="Category with single note",
        )
        session.add(cat)
        session.commit()
        session.refresh(cat)
        cat_id = cat.id

        note = Note(
            title="Single Note To Delete",
            content="Content for pruning test",
            vault_name="Vault",
            folder_path="folder",
            url=f"note://vault/folder/note-{cat_id}",
            is_frozen=0,
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id

        t_item = TaxonomyItem(
            category_id=cat_id,
            item_type="note",
            item_id=f"note_{note_id}",
            item_title=note.title,
            fit_score=0.9,
            assigned_at=now_str,
            item_class="Notes",
        )
        session.add(t_item)
        session.commit()

    resp = client.delete(f"/api/notes/{note_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert cat_id in data["cascaded"]["pruned_categories"]

    with db_session() as session:
        assert session.query(Note).filter_by(id=note_id).first() is None
        assert session.query(TaxonomyCategory).filter_by(id=cat_id).first() is None


def test_keep_category_if_other_notes_remain(client: TestClient):
    """If a category still contains other items, deleting one note does not prune the category."""
    now_str = datetime.now().isoformat()
    with db_session() as session:
        cat = TaxonomyCategory(
            name="Shared Category",
            slug=_unique_slug(session, "shared-cat"),
            item_count=2,
            doc="Category with 2 notes",
        )
        session.add(cat)
        session.commit()
        session.refresh(cat)
        cat_id = cat.id

        note1 = Note(
            title="Note One",
            content="Content 1",
            vault_name="Vault",
            folder_path="folder",
            url=f"note://vault/folder/n1-{cat_id}",
            is_frozen=0,
        )
        note2 = Note(
            title="Note Two",
            content="Content 2",
            vault_name="Vault",
            folder_path="folder",
            url=f"note://vault/folder/n2-{cat_id}",
            is_frozen=0,
        )
        session.add_all([note1, note2])
        session.commit()
        session.refresh(note1)
        session.refresh(note2)

        session.add_all([
            TaxonomyItem(category_id=cat_id, item_type="note", item_id=f"note_{note1.id}", item_title="Note One", fit_score=0.9, assigned_at=now_str, item_class="Notes"),
            TaxonomyItem(category_id=cat_id, item_type="note", item_id=f"note_{note2.id}", item_title="Note Two", fit_score=0.9, assigned_at=now_str, item_class="Notes"),
        ])
        session.commit()
        del_id = note1.id

    resp = client.delete(f"/api/notes/{del_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert cat_id not in data["cascaded"]["pruned_categories"]

    with db_session() as session:
        cat_db = session.query(TaxonomyCategory).filter_by(id=cat_id).first()
        assert cat_db is not None
        assert cat_db.item_count == 1


def test_recursive_parent_pruning_on_batch_delete(client: TestClient):
    """When a child category is pruned and its parent has no remaining items or children, parent is also pruned."""
    now_str = datetime.now().isoformat()
    with db_session() as session:
        parent = TaxonomyCategory(
            name="Parent Category",
            slug=_unique_slug(session, "parent-cat"),
            item_count=0,
            is_container=1,
            doc="Parent container",
        )
        session.add(parent)
        session.commit()
        session.refresh(parent)
        parent_id = parent.id

        child = TaxonomyCategory(
            name="Child Category",
            slug=_unique_slug(session, "child-cat"),
            parent_id=parent_id,
            item_count=1,
            depth=1,
            doc="Child category",
        )
        session.add(child)
        session.commit()
        session.refresh(child)
        child_id = child.id

        note = Note(
            title="Child Note",
            content="Child content",
            vault_name="Vault",
            folder_path="folder",
            url=f"note://vault/folder/child-{child_id}",
            is_frozen=0,
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id

        session.add(
            TaxonomyItem(category_id=child_id, item_type="note", item_id=f"note_{note_id}", item_title="Child Note", fit_score=0.9, assigned_at=now_str, item_class="Notes")
        )
        session.commit()

    resp = client.request("DELETE", "/api/notes/batch", json={"note_ids": [note_id]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert child_id in data["pruned_categories"]
    assert parent_id in data["pruned_categories"]

    with db_session() as session:
        assert session.query(TaxonomyCategory).filter_by(id=child_id).first() is None
        assert session.query(TaxonomyCategory).filter_by(id=parent_id).first() is None
