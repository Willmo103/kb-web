"""Taxonomic models and layer-specific node metadata definitions."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TaxonomyLevel(str, Enum):
    """The 7 taxonomic classification levels.

    Pattern (Issue #126):
    1. Kingdom: General Topic ('News', 'Software Documentation', 'Blogpost/Article', 'Reference', 'Resource', 'Hobby/Leisure', etc.)
    2. Phylum: Primary Sub-Topic (e.g., 'Activism', 'Fishing', 'Official-Documentation')
    3. Class: Secondary Sub-Topic (e.g., 'Removal-Efforts', 'Ultralight', 'Supabase')
    4. Order: Content Source / Domain / Program Context
    5. Family: Content Theme / Section / Tag Cluster
    6. Genus: Unique Article Structural Identity
    7. Species: Unique Article / Fact Variant Identity
    """

    KINGDOM = "kingdom"
    PHYLUM = "phylum"
    CLASS = "class"
    ORDER = "order"
    FAMILY = "family"
    GENUS = "genus"
    SPECIES = "species"


class KingdomNodeInfo(BaseModel):
    """Layer-specific metadata for Kingdom: General Topic of Information."""

    sphere: str = Field(
        ...,
        description="General Topic: News | Software Documentation | Blogpost/Article | Reference | Resource | Hobby/Leisure",
    )
    governing_motive: str = Field(
        ..., description="The fundamental purpose this topic domain serves"
    )
    privacy_boundary: str = Field(
        default="internal",
        description="confidential | internal | public | employer_bound",
    )
    temporal_decay: str = Field(
        default="slow",
        description="Rate of obsolescence: instant | rapid | moderate | slow | permanent",
    )


class PhylumNodeInfo(BaseModel):
    """Layer-specific metadata for Phylum: Primary Sub-Topic."""

    substrate: str = Field(
        ..., description="Primary sub-topic category (e.g. Fishing, Activism, Official Documentation)"
    )
    lifecycle: str = Field(
        default="continuous",
        description="continuous | transient | event_driven | static",
    )
    maintainer_role: str = Field(
        default="author",
        description="author | sysadmin | employee | steward | observer",
    )


class ClassNodeInfo(BaseModel):
    """Layer-specific metadata for Class: Secondary Sub-Topic."""

    interaction_pattern: str = Field(
        ...,
        description="Secondary sub-topic specialization (e.g. Ultralight, Removal-Efforts, Supabase)",
    )
    primary_technology: str = Field(
        ...,
        description="Domain specialization or subject stack",
    )
    protocol: Optional[str] = Field(
        default=None, description="http | ssh | mqtt | ipc | filesystem"
    )


class OrderNodeInfo(BaseModel):
    """Layer-specific metadata for Order: Article Source / Publisher / Domain."""

    program_slug: str = Field(..., description="Canonical source domain, publisher, or repository slug")
    origin_anchor: Optional[str] = Field(
        default=None, description="Git remote, vault root path, or network host"
    )
    maturity_stage: str = Field(
        default="active",
        description="prototype | active | stable | maintenance | archived",
    )
    lead_architect: str = Field(default="Will Morris")


class FamilyNodeInfo(BaseModel):
    """Layer-specific metadata for Family: Article Content Theme & Section Cluster."""

    cluster_name: str = Field(..., description="Content theme or tag cluster identifier")
    responsibility: str = Field(
        ..., description="Single crisp sentence on the family's sole responsibility"
    )
    dependencies: List[str] = Field(
        default_factory=list, description="Related families required for operation"
    )


class GenusNodeInfo(BaseModel):
    """Layer-specific metadata for Genus: Unique Article Structural Identity."""

    pattern_type: str = Field(
        ...,
        description="Unique article-level structural identifier",
    )
    template_id: Optional[str] = Field(
        default=None, description="Jinja or frontmatter template identifier"
    )
    required_frontmatter: List[str] = Field(
        default_factory=list, description="Fields required when serialized to markdown"
    )


class SpeciesNodeInfo(BaseModel):
    """Layer-specific metadata for Species: Unique Article Concrete Identity."""

    canonical_id: str = Field(
        ..., description="Unique article slug across entire personal context"
    )
    physical_location: str = Field(
        ...,
        description="Filesystem path, DB table, or remote URL (decoupled from taxonomy)",
    )
    content_fingerprint: Optional[str] = Field(
        default=None, description="SHA-256 hash or version tag"
    )
    frontmatter: Dict[str, Any] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TaxonomyPath(BaseModel):
    """Canonical 7-level taxonomic classification coordinates."""

    kingdom: str = Field(
        ..., description="General Topic (e.g. News, Software Documentation, Blogpost/Article, Reference, Resource, Hobby/Leisure)"
    )
    phylum: str = Field(
        ..., description="Sub-Topic Level 1 (e.g. Activism, Fishing, Official-Documentation)"
    )
    class_: str = Field(
        ...,
        alias="class",
        description="Sub-Topic Level 2 (e.g. Removal-Efforts, Ultralight, Supabase)",
    )
    order: str = Field(
        ..., description="Source / Domain Context (e.g. docs_python_org, github_com, youtube)"
    )
    family: str = Field(
        ..., description="Content Theme / Tag Cluster (e.g. sqlite3, authentication, ultralight_gear)"
    )
    genus: str = Field(
        ..., description="Unique Article Genus Identifier"
    )
    species: str = Field(
        ...,
        description="Unique Article Species Identifier",
    )

    model_config = {
        "populate_by_name": True,
    }

    def to_path_string(self, delimiter: str = "/") -> str:
        """Render to delimited string: kingdom/phylum/class/order/family/genus/species."""
        return delimiter.join(
            [
                self.kingdom,
                self.phylum,
                self.class_,
                self.order,
                self.family,
                self.genus,
                self.species,
            ]
        )

    @classmethod
    def from_string(cls, path_str: str, delimiter: str = "/") -> "TaxonomyPath":
        """Parse from delimited string."""
        clean_str = path_str.replace("::", "/").replace(" > ", "/")
        if "/" not in clean_str and "." in clean_str:
            clean_str = clean_str.replace(".", "/")
        parts = [p.strip() for p in clean_str.split(delimiter) if p.strip()]
        if len(parts) < 7:
            while len(parts) < 7:
                parts.append("general")
        return cls(
            kingdom=parts[0],
            phylum=parts[1],
            class_=parts[2],
            order=parts[3],
            family=parts[4],
            genus=parts[5],
            species=parts[6],
        )

    def to_frontmatter_dict(self) -> Dict[str, Any]:
        """Convert into Markdown YAML frontmatter dictionary."""
        return {
            "taxonomy": {
                "path": self.to_path_string("/"),
                "kingdom": self.kingdom,
                "phylum": self.phylum,
                "class": self.class_,
                "order": self.order,
                "family": self.family,
                "genus": self.genus,
                "species": self.species,
            }
        }


class TaxonomyEntityRecord(BaseModel):
    """Pydantic model representing a registered taxonomy entity."""

    canonical_id: str
    taxonomy_path: str
    kingdom: Optional[str] = None
    phylum: Optional[str] = None
    class_name: Optional[str] = None
    order_name: Optional[str] = None
    family: Optional[str] = None
    genus: Optional[str] = None
    species: Optional[str] = None
    physical_location: str
    attributes: Dict[str, Any] = Field(default_factory=dict)
    updated_at: str
