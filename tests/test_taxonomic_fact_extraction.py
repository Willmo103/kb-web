"""Unit and integration test suite for 7-tier biological taxonomy and context fact extraction mesh."""

import json
from unittest.mock import MagicMock, patch
import pytest

from kb_web.taxonomy.models import (
    TaxonomyLevel,
    TaxonomyPath,
    KingdomNodeInfo,
    PhylumNodeInfo,
    ClassNodeInfo,
    OrderNodeInfo,
    FamilyNodeInfo,
    GenusNodeInfo,
    SpeciesNodeInfo,
)
from kb_web.taxonomy.engine import TaxonomyEngine, TaxonomyClassifier
from kb_web.context_mesh.models import (
    ContextStatement,
    EvalStatus,
    StatementType,
    TaxonomicLayer,
)
from kb_web.context_mesh.store import ContextStore, cosine_similarity
from kb_web.context_mesh.pipeline import FactExtractionPipeline
from kb_web.context_mesh.retriever import BubbleDownRetriever
from kb_web.context_mesh.injector import (
    SubconsciousContextInjector,
    get_subconscious_injector,
    auto_inject_subconscious_context,
)
from kb_web.worker import AutonomousWorker


def test_taxonomy_path_serialization_and_parsing():
    """Verify 7-tier TaxonomyPath serialization and parsing."""
    path = TaxonomyPath(
        kingdom="knowledge",
        phylum="text",
        class_="human_read",
        order="kb_web",
        family="architecture",
        genus="ArticleWiki",
        species="embedding_unification",
    )
    path_str = path.to_path_string("/")
    assert path_str == "knowledge/text/human_read/kb_web/architecture/ArticleWiki/embedding_unification"

    parsed = TaxonomyPath.from_string(path_str)
    assert parsed.kingdom == "knowledge"
    assert parsed.phylum == "text"
    assert parsed.class_ == "human_read"
    assert parsed.order == "kb_web"
    assert parsed.family == "architecture"
    assert parsed.genus == "ArticleWiki"
    assert parsed.species == "embedding_unification"

    # Test padding with generic tokens when fewer than 7 levels are provided
    short_parsed = TaxonomyPath.from_string("knowledge/text/human_read")
    assert short_parsed.kingdom == "knowledge"
    assert short_parsed.phylum == "text"
    assert short_parsed.class_ == "human_read"
    assert short_parsed.order == "general"
    assert short_parsed.family == "general"
    assert short_parsed.genus == "general"
    assert short_parsed.species == "general"

    # Test frontmatter dict
    fm = path.to_frontmatter_dict()
    assert fm["taxonomy"]["path"] == path_str
    assert fm["taxonomy"]["order"] == "kb_web"


def test_taxonomy_classifier():
    """Verify TaxonomyClassifier infers correct 7-tier coordinates."""
    # Web article
    art_path = TaxonomyClassifier.classify_article(
        url="https://docs.python.org/3/library/sqlite3.html",
        title="sqlite3 — DB-API 2.0 interface for SQLite databases",
        tags=["database", "python"],
    )
    assert art_path.kingdom == "knowledge"
    assert art_path.phylum == "text"
    assert art_path.class_ == "human_read"
    assert "docs_python_org" in art_path.order
    assert art_path.family == "database"
    assert art_path.genus == "ArticleWiki"

    # Git repo
    repo_path = TaxonomyClassifier.classify_git_repo("kb-web", "https://github.com/Willmo103/kb-web.git")
    assert repo_path.kingdom == "software"
    assert repo_path.phylum == "code"
    assert repo_path.class_ == "cli_command"
    assert repo_path.order == "kb_web"
    assert repo_path.genus == "Repository"

    # YouTube video
    video_path = TaxonomyClassifier.classify_youtube_video(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Rick Astley - Never Gonna Give You Up",
        creator="RickAstleyVEVO",
    )
    assert video_path.kingdom == "knowledge"
    assert video_path.phylum == "media"
    assert video_path.class_ == "video_stream"
    assert video_path.genus == "YouTubeVideo"

    # Note
    note_path = TaxonomyClassifier.classify_note(
        title="Memory Architecture Strategy",
        tags=["design", "agents"],
    )
    assert note_path.kingdom == "knowledge"
    assert note_path.class_ == "daily_notes"
    assert note_path.family == "design"
    assert note_path.genus == "Note"


def test_taxonomy_engine_persistence():
    """Verify TaxonomyEngine registers and queries entities."""
    engine = TaxonomyEngine()
    path = TaxonomyPath(
        kingdom="software",
        phylum="code",
        class_="rest_api",
        order="orcastrator",
        family="context",
        genus="Store",
        species="ContextStore",
    )

    entity = engine.register_entity(
        taxonomy=path,
        physical_location="src/kb_web/context_mesh/store.py",
        attributes={"version": "1.0", "author": "Will"},
    )
    assert entity.canonical_id == path.to_path_string("/")
    assert entity.kingdom == "software"
    assert entity.order_name == "orcastrator"

    fetched = engine.get_entity(path.to_path_string("/"))
    assert fetched is not None
    assert fetched.physical_location == "src/kb_web/context_mesh/store.py"

    results = engine.list_entities(kingdom="software", order="orcastrator")
    assert any(e.canonical_id == path.to_path_string("/") for e in results)


def test_cosine_similarity():
    """Verify cosine similarity calculation."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert cosine_similarity(v1, v2) == pytest.approx(1.0)

    v3 = [0.0, 1.0, 0.0]
    assert cosine_similarity(v1, v3) == pytest.approx(0.0)

    v4 = [1.0, 1.0, 0.0]
    assert cosine_similarity(v1, v4) == pytest.approx(0.7071, abs=1e-3)


def test_context_store_crud_and_evaluations():
    """Verify ContextStore CRUD, review statuses, and dynamic exemplars."""
    store = ContextStore()

    stmt = ContextStatement(
        id="stmt_test_001",
        statement="All embedding operations must utilize the active unified model.",
        statement_type=StatementType.NEGATIVE_INVARIANT,
        canonical_path="knowledge/text/human_read/kb_web/architecture/ArticleWiki/embedding_rule",
        layer_level=TaxonomicLayer.ORDER,
        source_uri="https://github.com/Willmo103/kb-web/docs/embeddings.md",
        source_title="Embedding Unification Guide",
        confidence=0.95,
        embedding=[0.1, 0.2, 0.3, 0.4],
        tags=["embeddings", "rules"],
        metadata={"priority": "high"},
    )

    store.upsert(stmt)

    retrieved = store.get_by_id("stmt_test_001")
    assert retrieved is not None
    assert retrieved.statement == stmt.statement
    assert retrieved.statement_type == StatementType.NEGATIVE_INVARIANT
    assert retrieved.layer_level == TaxonomicLayer.ORDER
    assert retrieved.score_rank == 3.0
    assert retrieved.eval_status == EvalStatus.UNREVIEWED

    # Test markdown citation
    citation = retrieved.to_citation_markdown()
    assert "- **[NEGATIVE_INVARIANT]**" in citation
    assert "[Source: Embedding Unification Guide](https://github.com/Willmo103/kb-web/docs/embeddings.md)" in citation

    # Upvote statement to 4.8 stars (should auto-promote to APPROVED)
    updated = store.update_evaluation("stmt_test_001", score=4.8, feedback="Essential architectural rule")
    assert updated.score_rank == 4.8
    assert updated.eval_status == EvalStatus.APPROVED
    assert updated.eval_count == 1
    assert updated.eval_feedback == "Essential architectural rule"

    # Add a rejected anti-pattern
    bad_stmt = ContextStatement(
        id="stmt_test_002",
        statement="Querying with comic against Gemma embedding is acceptable.",
        statement_type=StatementType.FACT,
        canonical_path="knowledge/text/human_read/kb_web/architecture/ArticleWiki/bad_pattern",
        layer_level=TaxonomicLayer.SPECIES,
        source_uri="https://example.com/err",
        source_title="Outdated Note",
        confidence=0.4,
        embedding=[0.9, 0.1, 0.0, 0.0],
    )
    store.upsert(bad_stmt)
    store.update_evaluation("stmt_test_002", score=1.2, feedback="Causes vector corruption")

    # Fetch exemplars
    positives, negatives = store.get_exemplars(positive_limit=5, negative_limit=5)
    assert any(p.id == "stmt_test_001" for p in positives)
    assert any(n.id == "stmt_test_002" for n in negatives)

    # Vector search with composite ranking
    # Query vector close to stmt_test_001
    results = store.search_by_vector(query_vector=[0.1, 0.2, 0.3, 0.4], top_k=5)
    assert len(results) > 0
    top_stmt, top_score = results[0]
    assert top_stmt.id == "stmt_test_001"
    assert top_score > 0.8
    # stmt_test_002 is rejected and should be suppressed by default
    assert not any(s.id == "stmt_test_002" for s, _ in results)


def test_fact_extraction_pipeline_dynamic_prompt():
    """Verify FactExtractionPipeline builds dynamic prompt with positive and negative exemplars."""
    store = ContextStore()
    pipeline = FactExtractionPipeline(store=store)

    system_prompt = pipeline.build_system_prompt()
    assert "Personal Context & Intent Extraction Engine" in system_prompt
    assert "GOLD-STANDARD EXEMPLARS" in system_prompt
    assert "OFF-BASE ANTI-PATTERNS" in system_prompt
    assert "All embedding operations must utilize the active unified model." in system_prompt
    assert "Querying with comic against Gemma embedding is acceptable." in system_prompt


def test_fact_extraction_pipeline_with_mock_ollama():
    """Verify extraction workflow with mocked Ollama LLM and embedding calls."""
    mock_client = MagicMock()
    mock_client.list.return_value = {"models": [{"name": "ornith-1.5:9b"}, {"name": "nomic-embed-text"}]}
    mock_client.chat.return_value = {
        "message": {
            "content": json.dumps([
                {
                    "statement": "When configuring vectors, always match query model to indexing model.",
                    "statement_type": "negative_invariant",
                    "layer_level": "order",
                },
                {
                    "statement": "Users prefer direct prompt injection over manual vector retrieval.",
                    "statement_type": "preference",
                    "layer_level": "class",
                },
            ])
        }
    }
    mock_client.embeddings.return_value = {"embedding": [0.05, 0.15, 0.25, 0.35]}

    store = ContextStore()
    pipeline = FactExtractionPipeline(store=store, client=mock_client)

    statements = pipeline.extract_from_text(
        source_text="Documentation on agent prompt memory and embedding unification.",
        source_uri="https://kb.local/docs/memory",
        source_title="Agent Memory Documentation",
        canonical_path="knowledge/text/human_read/kb_web/memory/ArticleWiki/prompt_injection",
    )

    assert len(statements) == 2
    assert statements[0].statement_type == StatementType.NEGATIVE_INVARIANT
    assert statements[0].layer_level == TaxonomicLayer.ORDER
    assert statements[0].embedding == [0.05, 0.15, 0.25, 0.35]
    assert statements[1].statement_type == StatementType.PREFERENCE
    assert statements[1].layer_level == TaxonomicLayer.CLASS

    # Check persistence in database
    persisted = store.get_by_id(statements[0].id)
    assert persisted is not None
    assert persisted.statement == statements[0].statement


def test_fact_extraction_heuristic_fallback():
    """Verify heuristic rule-based extraction works gracefully when Ollama fails."""
    mock_client = MagicMock()
    mock_client.list.side_effect = ConnectionError("Ollama daemon unreachable")
    mock_client.chat.side_effect = ConnectionError("Ollama daemon unreachable")
    mock_client.embeddings.side_effect = ConnectionError("Ollama daemon unreachable")

    store = ContextStore()
    pipeline = FactExtractionPipeline(store=store, client=mock_client)

    sample_doc = (
        "Hierarchical bubble-down retrieval enables seamless context routing.\n"
        "Embedding models must remain unified across database columns.\n"
        "Atomic context statements retain hard clickable source provenance citations."
    )

    statements = pipeline.extract_from_text(
        source_text=sample_doc,
        source_uri="https://kb.local/docs/architecture",
        source_title="Architecture Overview",
        canonical_path="knowledge/text/human_read/kb_web/architecture/ArticleWiki/overview",
    )

    assert len(statements) >= 2
    for s in statements:
        assert s.statement_type == StatementType.FACT
        assert s.layer_level == TaxonomicLayer.SPECIES
        assert len(s.statement) > 20


def test_bubble_down_retriever_decision_routing():
    """Verify BubbleDownRetriever routes Kingdom & Phylum using d1 decision model."""
    mock_client = MagicMock()
    mock_client.systemone.return_value = {
        "answers": {
            "kingdom": {"choice": "software", "score": 0.96},
            "phylum": {"choice": "code", "score": 0.94},
        }
    }

    retriever = BubbleDownRetriever(client=mock_client)
    kingdom, phylum, conf = retriever.route_kingdom_and_phylum("Where is the Git repository shallow clone logic?")

    assert kingdom == "software"
    assert phylum == "code"
    assert conf == pytest.approx(0.96)


def test_bubble_down_retriever_heuristic_routing():
    """Verify BubbleDownRetriever heuristic fallback routing when decision model is offline."""
    mock_client = MagicMock()
    mock_client.systemone.side_effect = RuntimeError("d1 model not loaded")

    retriever = BubbleDownRetriever(client=mock_client)

    k1, p1, _ = retriever.route_kingdom_and_phylum("Fix git branch merge issue in python script")
    assert k1 == "software"
    assert p1 == "code"

    k2, p2, _ = retriever.route_kingdom_and_phylum("Restart docker container and postgresql database")
    assert k2 == "infrastructure"
    assert p2 == "tooling"

    k3, p3, _ = retriever.route_kingdom_and_phylum("Watch youtube video lecture transcript")
    assert k3 == "knowledge"
    assert p3 == "media"


def test_bubble_down_retriever_hierarchical_traversal():
    """Verify multi-tier context statement retrieval and formatted context block."""
    store = ContextStore()

    # Seed statements across layers
    top_stmt = ContextStatement(
        id="stmt_hier_001",
        statement="All code packages must maintain standalone test suites.",
        statement_type=StatementType.NEGATIVE_INVARIANT,
        canonical_path="software/code/cli_command/kb_web/general/Package/rule",
        layer_level=TaxonomicLayer.KINGDOM,
        source_uri="https://kb.local/docs/dev_rules",
        source_title="Development Rules",
        confidence=1.0,
        embedding=[0.2, 0.4, 0.6, 0.8],
        score_rank=4.5,
        eval_status=EvalStatus.APPROVED,
    )
    store.upsert(top_stmt)

    ground_stmt = ContextStatement(
        id="stmt_hier_002",
        statement="When cloning repos, always execute shallow clone with depth 1.",
        statement_type=StatementType.PREFERENCE,
        canonical_path="software/code/cli_command/kb_web/repo_importer/RepoScanner/shallow_clone",
        layer_level=TaxonomicLayer.SPECIES,
        source_uri="https://kb.local/docs/repo_importer",
        source_title="Repo Importer Docs",
        confidence=0.95,
        embedding=[0.22, 0.38, 0.61, 0.79],
        score_rank=4.2,
        eval_status=EvalStatus.APPROVED,
    )
    store.upsert(ground_stmt)

    mock_client = MagicMock()
    mock_client.systemone.return_value = {
        "answers": {
            "kingdom": {"choice": "software", "score": 0.95},
            "phylum": {"choice": "code", "score": 0.92},
        }
    }
    mock_client.embeddings.return_value = {"embedding": [0.2, 0.4, 0.6, 0.8]}

    retriever = BubbleDownRetriever(store=store, client=mock_client)
    assembled = retriever.retrieve("How should git repositories be cloned?")

    assert assembled.routed_kingdom == "software"
    assert assembled.routed_phylum == "code"
    assert len(assembled.statements) >= 2
    assert any(s.id == "stmt_hier_001" for s in assembled.statements)
    assert any(s.id == "stmt_hier_002" for s in assembled.statements)
    assert "<subconscious_context>" not in assembled.formatted_context_block
    assert "Development Rules" in assembled.formatted_context_block
    assert "Repo Importer Docs" in assembled.formatted_context_block


def test_subconscious_context_injector():
    """Verify SubconsciousContextInjector embeds formatted XML block into agent prompt."""
    store = ContextStore()
    retriever_mock = MagicMock()
    retriever_mock.retrieve.return_value.statements = [
        ContextStatement(
            id="stmt_inj_001",
            statement="Database vector columns use SafeVector for cross-engine compatibility.",
            statement_type=StatementType.FACT,
            canonical_path="software/code/cli_command/kb_web/models/SafeVector/fact",
            layer_level=TaxonomicLayer.ORDER,
            source_uri="https://kb.local/models_orm",
            source_title="ORM Architecture",
        )
    ]
    retriever_mock.retrieve.return_value.formatted_context_block = (
        "### Personal Intent & Operational Context for: 'ORM'\n"
        "- **[FACT]** Database vector columns use SafeVector. *([Source: ORM Architecture](https://kb.local/models_orm))*"
    )

    injector = SubconsciousContextInjector(retriever=retriever_mock)
    base_prompt = "You are a helpful coding assistant for kb-web."
    injected, assembled = injector.inject_subconscious_context(base_prompt, "Explain the database models")

    assert "<subconscious_context>" in injected
    assert "</subconscious_context>" in injected
    assert "SafeVector" in injected
    assert "ORM Architecture" in injected


@pytest.mark.anyio
async def test_worker_fact_extraction_job():
    """Verify the fact_extraction ServerJob is properly registered in AutonomousWorker."""
    worker = AutonomousWorker()
    assert "fact_extraction" in worker.jobs
    job = worker.jobs["fact_extraction"]
    assert job.name == "Context Fact Extraction Agent"
    assert job.category == "llm"
    assert job.interval_minutes == 15

    # Mock runner execution with empty database
    res = await worker.run_job("fact_extraction")
    assert res.get("status") in ("noop", "success", "skipped")

