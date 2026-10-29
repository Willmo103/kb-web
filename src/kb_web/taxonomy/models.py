"""Taxonomic models and layer-specific node metadata definitions."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TaxonomyLevel(str, Enum):
    """The 7 biological-inspired taxonomic classification levels."""

    KINGDOM = "kingdom"
    PHYLUM = "phylum"
    CLASS = "class"
    ORDER = "order"
    FAMILY = "family"
    GENUS = "genus"
    SPECIES = "species"


class KingdomNodeInfo(BaseModel):
    """Layer-specific metadata for Kingdom: Spheres of Reality."""

    sphere: str = Field(
        ...,
        description="personal | professional | software | knowledge | infrastructure",
    )
    governing_motive: str = Field(
        ..., description="The fundamental purpose this sphere serves"
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
    """Layer-specific metadata for Phylum: Subsystem Medium & Execution Substrate."""

    substrate: str = Field(
        ..., description="code | text | hardware | network | currency | biology | media"
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
    """Layer-specific metadata for Class: Modality of Interaction & Technology Stack."""

    interaction_pattern: str = Field(
        ...,
        description="cli_command | rest_api | human_read | automated_poll | video_stream",
    )
    primary_technology: str = Field(
        ...,
        description="python | typescript | markdown | docker | homeassistant | sqlite | postgres",
    )
    protocol: Optional[str] = Field(
        default=None, description="http | ssh | mqtt | ipc | filesystem"
    )


class OrderNodeInfo(BaseModel):
    """Layer-specific metadata for Order: Bounded Context, Program & Organization Unit."""

    program_slug: str = Field(..., description="Canonical program or initiative slug")
    origin_anchor: Optional[str] = Field(
        default=None, description="Git remote, vault root path, or network host"
    )
    maturity_stage: str = Field(
        default="active",
        description="prototype | active | stable | maintenance | archived",
    )
    lead_architect: str = Field(default="Will Morris")


class FamilyNodeInfo(BaseModel):
    """Layer-specific metadata for Family: Functional Cohesion & Component Cluster."""

    cluster_name: str = Field(..., description="Functional group identifier")
    responsibility: str = Field(
        ..., description="Single crisp sentence on the family's sole responsibility"
    )
    dependencies: List[str] = Field(
        default_factory=list, description="Related families required for operation"
    )


class GenusNodeInfo(BaseModel):
    """Layer-specific metadata for Genus: Structural Pattern & Template Type."""

    pattern_type: str = Field(
        ...,
        description="class_declaration | markdown_document | json_schema | executable_script | article_wiki",
    )
    template_id: Optional[str] = Field(
        default=None, description="Jinja or frontmatter template identifier"
    )
    required_frontmatter: List[str] = Field(
        default_factory=list, description="Fields required when serialized to markdown"
    )


class SpeciesNodeInfo(BaseModel):
    """Layer-specific metadata for Species: Concrete Entity Identity."""

    canonical_id: str = Field(
        ..., description="Unique slug across entire personal context"
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
        ..., description="Sphere of Reality (e.g. software, knowledge, infrastructure)"
    )
    phylum: str = Field(
        ..., description="Subsystem Medium (e.g. tooling, vault, iot, text, media)"
    )
    class_: str = Field(
        ...,
        alias="class",
        description="Interaction Modality (e.g. cli, daily_notes, human_read)",
    )
    order: str = Field(
        ..., description="Bounded Program Context (e.g. kb-web, orcastrator, devtul)"
    )
    family: str = Field(
        ..., description="Component Cluster (e.g. sources, architecture, routers)"
    )
    genus: str = Field(
        ..., description="Structural Pattern (e.g. ArticleWiki, RepoScanner, VaultNote)"
    )
    species: str = Field(
        ...,
        description="Concrete Entity Variant (e.g. embedding_unification, LocalGitScanner)",
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
        clean_str = path_str.replace("::", "/").replace(".", "/")
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
