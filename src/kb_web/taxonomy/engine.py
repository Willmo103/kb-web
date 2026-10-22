"""Taxonomic Classification Engine, Template Renderer, and Abstracted View Layer.

Maps physical assets (web pages, git repos, youtube videos, notes) into 7-tier
biological taxonomy coordinates and handles persistence in taxonomy_entities.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ..base import db_session
from ..models_orm import TaxonomyEntityORM
from .models import TaxonomyLevel, TaxonomyPath, TaxonomyEntityRecord


def slugify(text: str) -> str:
    """Produce a clean lowercase slug with alphanumeric chars and hyphens/underscores."""
    if not text:
        return "unnamed"
    s = re.sub(r"[^\w\s-]", "", text.strip().lower())
    s = re.sub(r"[-\s]+", "_", s)
    return s[:64] or "unnamed"


class TaxonomyClassifier:
    """Classifies physical context assets into 7-tier biological taxonomy coordinates."""

    @staticmethod
    def classify_article(
        url: str,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> TaxonomyPath:
        """Infer taxonomic coordinates for an ingested web article."""
        parsed = urlparse(url)
        host = (parsed.netloc or "web").replace(".", "_").replace(":", "_").lower()
        if host.startswith("www_"):
            host = host[4:]

        # Family from primary tag or default
        family = "general"
        if tags and len(tags) > 0:
            family = slugify(tags[0])

        title_slug = slugify(title or parsed.path or "article")

        return TaxonomyPath(
            kingdom="knowledge",
            phylum="text",
            class_="human_read",
            order=slugify(host),
            family=family,
            genus="ArticleWiki",
            species=title_slug,
        )

    @staticmethod
    def classify_git_repo(
        repo_name: str,
        remote_url: Optional[str] = None,
        path: Optional[str] = None,
    ) -> TaxonomyPath:
        """Infer taxonomic coordinates for a git repository."""
        clean_name = slugify(repo_name or "repo")
        return TaxonomyPath(
            kingdom="software",
            phylum="code",
            class_="rest_api" if "api" in clean_name else "cli_command",
            order=clean_name,
            family="core",
            genus="Repository",
            species=clean_name,
        )

    @staticmethod
    def classify_youtube_video(
        url: str,
        title: Optional[str] = None,
        creator: Optional[str] = None,
    ) -> TaxonomyPath:
        """Infer taxonomic coordinates for a YouTube video."""
        creator_slug = slugify(creator or "youtube_creator")
        title_slug = slugify(title or "video")
        return TaxonomyPath(
            kingdom="knowledge",
            phylum="media",
            class_="video_stream",
            order=creator_slug,
            family="video_lecture",
            genus="YouTubeVideo",
            species=title_slug,
        )

    @staticmethod
    def classify_note(
        title: str,
        tags: Optional[List[str]] = None,
    ) -> TaxonomyPath:
        """Infer taxonomic coordinates for a note or research memo."""
        family = "general"
        if tags and len(tags) > 0:
            family = slugify(tags[0])
        title_slug = slugify(title or "memo")
        return TaxonomyPath(
            kingdom="knowledge",
            phylum="text",
            class_="daily_notes",
            order="kb_web",
            family=family,
            genus="Note",
            species=title_slug,
        )


class TaxonomyEngine:
    """Persistence, template generation, and abstract view querying."""

    @staticmethod
    def _orm_to_record(orm: TaxonomyEntityORM) -> TaxonomyEntityRecord:
        attr = {}
        if orm.attributes_json:
            try:
                parsed = json.loads(orm.attributes_json)
                if isinstance(parsed, dict):
                    attr = parsed
            except Exception:
                pass
        return TaxonomyEntityRecord(
            canonical_id=orm.canonical_id,
            taxonomy_path=orm.taxonomy_path,
            kingdom=orm.kingdom,
            phylum=orm.phylum,
            class_name=orm.class_name,
            order_name=orm.order_name,
            family=orm.family,
            genus=orm.genus,
            species=orm.species,
            physical_location=orm.physical_location,
            attributes=attr,
            updated_at=orm.updated_at,
        )

    def register_entity(
        self,
        taxonomy: TaxonomyPath,
        physical_location: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> TaxonomyEntityRecord:
        """Upsert an entity and its taxonomic coordinates into the database."""
        canonical_id = taxonomy.to_path_string("/")
        now_iso = datetime.now(timezone.utc).isoformat()
        attr_json = json.dumps(attributes or {})

        with db_session() as session:
            entity = session.query(TaxonomyEntityORM).filter_by(canonical_id=canonical_id).first()
            if entity:
                entity.taxonomy_path = canonical_id
                entity.kingdom = taxonomy.kingdom
                entity.phylum = taxonomy.phylum
                entity.class_name = taxonomy.class_
                entity.order_name = taxonomy.order
                entity.family = taxonomy.family
                entity.genus = taxonomy.genus
                entity.species = taxonomy.species
                entity.physical_location = physical_location
                entity.attributes_json = attr_json
                entity.updated_at = now_iso
            else:
                entity = TaxonomyEntityORM(
                    canonical_id=canonical_id,
                    taxonomy_path=canonical_id,
                    kingdom=taxonomy.kingdom,
                    phylum=taxonomy.phylum,
                    class_name=taxonomy.class_,
                    order_name=taxonomy.order,
                    family=taxonomy.family,
                    genus=taxonomy.genus,
                    species=taxonomy.species,
                    physical_location=physical_location,
                    attributes_json=attr_json,
                    updated_at=now_iso,
                )
                session.add(entity)
            session.commit()
            return self._orm_to_record(entity)

    def get_entity(self, canonical_id: str) -> Optional[TaxonomyEntityRecord]:
        """Fetch an entity by canonical taxonomy path ID."""
        with db_session() as session:
            orm = session.query(TaxonomyEntityORM).filter_by(canonical_id=canonical_id).first()
            if not orm:
                return None
            return self._orm_to_record(orm)

    def list_entities(
        self,
        kingdom: Optional[str] = None,
        phylum: Optional[str] = None,
        order: Optional[str] = None,
        family: Optional[str] = None,
        limit: int = 100,
    ) -> List[TaxonomyEntityRecord]:
        """Query taxonomy entities filtered by biological coordinates."""
        with db_session() as session:
            q = session.query(TaxonomyEntityORM)
            if kingdom:
                q = q.filter(TaxonomyEntityORM.kingdom == kingdom)
            if phylum:
                q = q.filter(TaxonomyEntityORM.phylum == phylum)
            if order:
                q = q.filter(TaxonomyEntityORM.order_name == order)
            if family:
                q = q.filter(TaxonomyEntityORM.family == family)
            q = q.order_by(TaxonomyEntityORM.updated_at.desc()).limit(limit)
            return [self._orm_to_record(r) for r in q.all()]

    def sync_entities_from_library(self, limit: int = 1000) -> Dict[str, Any]:
        """Backfill and register 7-tier biological taxonomy coordinates for all library items and notes."""
        from ..models_orm import FetchedPage, Note

        synced_pages = 0
        synced_notes = 0

        with db_session() as session:
            # Sync fetched pages
            pages = session.query(FetchedPage).limit(limit).all()
            for page in pages:
                url = page.url or ""
                title = page.title or url
                tags = []
                if page.tags:
                    try:
                        parsed = json.loads(page.tags)
                        if isinstance(parsed, list):
                            tags = parsed
                    except Exception:
                        tags = [t.strip() for t in str(page.tags).split(",") if t.strip()]

                if "youtube.com" in url or "youtu.be" in url:
                    tax = TaxonomyClassifier.classify_youtube_video(url=url, title=title)
                elif url.startswith("repo://") or "git" in tags or "repo" in tags:
                    tax = TaxonomyClassifier.classify_git_repo(repo_name=title, remote_url=url)
                elif url.startswith("note://"):
                    tax = TaxonomyClassifier.classify_note(title=title, tags=tags)
                else:
                    tax = TaxonomyClassifier.classify_article(url=url, title=title, tags=tags, description=page.description)

                self.register_entity(
                    taxonomy=tax,
                    physical_location=url,
                    attributes={"title": title, "tags": tags, "source_type": "page"},
                )
                synced_pages += 1

            # Sync notes
            notes = session.query(Note).limit(limit).all()
            for note in notes:
                note_title = note.title or f"note_{note.id}"
                note_url = note.url or f"note://{note.vault_name or 'PersonalVault'}/{note_title}"
                note_tags = []
                if note.tags:
                    try:
                        parsed = json.loads(note.tags)
                        if isinstance(parsed, list):
                            note_tags = parsed
                    except Exception:
                        note_tags = [t.strip() for t in str(note.tags).split(",") if t.strip()]

                tax = TaxonomyClassifier.classify_note(title=note_title, tags=note_tags)
                self.register_entity(
                    taxonomy=tax,
                    physical_location=note_url,
                    attributes={"title": note_title, "tags": note_tags, "source_type": "note"},
                )
                synced_notes += 1

        return {
            "status": "success",
            "synced_pages": synced_pages,
            "synced_notes": synced_notes,
            "total_synced": synced_pages + synced_notes,
        }

    def get_7tier_tree(self) -> Dict[str, Any]:
        """Builds hierarchical 7-tier biological taxonomy tree populated from taxonomy_entities and context_statements."""
        from ..models_orm import ContextStatementORM, TaxonomyEntityORM

        tree: Dict[str, Any] = {}
        total_entities = 0
        total_statements = 0

        with db_session() as session:
            entities = session.query(TaxonomyEntityORM).all()
            total_entities = len(entities)

            # Pre-aggregate statements by kingdom / phylum / order
            stmt_rows = session.query(
                ContextStatementORM.canonical_path,
                ContextStatementORM.kingdom,
                ContextStatementORM.phylum,
                ContextStatementORM.order_name,
                ContextStatementORM.family,
            ).all()
            total_statements = len(stmt_rows)

            stmt_counts: Dict[str, int] = {}
            for r in stmt_rows:
                k = r[1] or "general"
                p = r[2] or "general"
                o = r[3] or "general"
                stmt_counts[f"{k}"] = stmt_counts.get(f"{k}", 0) + 1
                stmt_counts[f"{k}/{p}"] = stmt_counts.get(f"{k}/{p}", 0) + 1
                stmt_counts[f"{k}/{p}/{o}"] = stmt_counts.get(f"{k}/{p}/{o}", 0) + 1

            for e in entities:
                k = e.kingdom or "knowledge"
                p = e.phylum or "general"
                c = e.class_name or "general"
                o = e.order_name or "general"
                f = e.family or "general"

                if k not in tree:
                    tree[k] = {
                        "name": k,
                        "level": "kingdom",
                        "path": k,
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(k, 0),
                        "phyla": {},
                    }
                tree[k]["entity_count"] += 1

                phyla = tree[k]["phyla"]
                if p not in phyla:
                    phyla[p] = {
                        "name": p,
                        "level": "phylum",
                        "path": f"{k}/{p}",
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(f"{k}/{p}", 0),
                        "orders": {},
                    }
                phyla[p]["entity_count"] += 1

                orders = phyla[p]["orders"]
                if o not in orders:
                    orders[o] = {
                        "name": o,
                        "level": "order",
                        "path": f"{k}/{p}/{o}",
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(f"{k}/{p}/{o}", 0),
                        "families": {},
                    }
                orders[o]["entity_count"] += 1

                families = orders[o]["families"]
                if f not in families:
                    families[f] = {
                        "name": f,
                        "level": "family",
                        "path": f"{k}/{p}/{o}/{f}",
                        "entity_count": 0,
                        "statement_count": 0,
                        "entities": [],
                    }
                families[f]["entity_count"] += 1
                if len(families[f]["entities"]) < 50:
                    families[f]["entities"].append(self._orm_to_record(e).model_dump())

        return {
            "total_entities": total_entities,
            "total_statements": total_statements,
            "tree": tree,
        }

    def to_yaml_frontmatter(self, taxonomy: TaxonomyPath) -> str:
        """Render markdown YAML frontmatter string."""
        return (
            "---\n"
            "taxonomy:\n"
            f"  path: \"{taxonomy.to_path_string('/')}\"\n"
            f"  kingdom: \"{taxonomy.kingdom}\"\n"
            f"  phylum: \"{taxonomy.phylum}\"\n"
            f"  class: \"{taxonomy.class_}\"\n"
            f"  order: \"{taxonomy.order}\"\n"
            f"  family: \"{taxonomy.family}\"\n"
            f"  genus: \"{taxonomy.genus}\"\n"
            f"  species: \"{taxonomy.species}\"\n"
            "---\n"
        )


