"""Taxonomica - A taxonomy-based guessing game exploring the tree of life."""

__version__ = "0.1.0"

# Wikipedia DwC-A parser (incomplete hierarchies)
from taxonomica.dwca import (
    DarwinCoreArchive,
    Description,
    Multimedia,
    SpeciesProfile,
    Taxon,
    TypeSpecimen,
    VernacularName,
)
from taxonomica.taxonomy import MAJOR_RANKS, RANK_PRIORITY, TaxonNode, TaxonomyTree
from taxonomica.tree import TaxonomyNode as DwCATaxonomyNode
from taxonomica.tree import TaxonomyTree as DwCATaxonomyTree

# GBIF Backbone parser (complete hierarchies) - recommended
from taxonomica.gbif_backbone import (
    GBIFBackbone,
    GBIFMultimedia,
    GBIFTaxon,
    GBIFVernacularName,
)
from taxonomica.gbif_tree import GBIFTaxonomyTree
from taxonomica.gbif_tree import TaxonomyNode as GBIFTaxonomyNode

# ColDP parser and tree builder (experimental new data pipeline)
from taxonomica.candidate_tree import (
    CandidateMatch,
    CandidateSpecies,
    CandidateTreeBuildResult,
    MajorRankPath,
    build_candidate_tree,
    extract_gbif_ids,
)
from taxonomica.coldp import (
    ColdPArchive,
    ColdPMedia,
    ColdPNameUsage,
    ColdPVernacularName,
)
from taxonomica.coldp_profile import ColdPProfile, ColdPProfileRecord, profile_archive
from taxonomica.coldp_sqlite import (
    ColdPSQLiteStore,
    ColdPSQLiteTaxon,
    build_sqlite_index,
    default_sqlite_path,
)
from taxonomica.coldp_tree import ColdPTaxonomyNode, ColdPTaxonomyTree

# Wikipedia description loader
from taxonomica.wikipedia import (
    WikipediaData,
    WikipediaDescription,
    WikipediaSpecies,
)

# Redaction engine for gameplay
from taxonomica.redaction import (
    Redactor,
    RedactionTerms,
    build_redaction_terms_from_node,
    build_redaction_terms_manual,
)

# Popularity scoring for difficulty levels
from taxonomica.popularity import (
    PopularityIndex,
    PopularityMetrics,
)
from taxonomica.runtime_db import (
    RuntimeDescription,
    RuntimeTaxonomyData,
)

# Playable command-line game
from taxonomica.game import (
    TaxonomicaGame,
    get_rank_title,
    get_seed_from_string,
    select_playable_species,
    split_into_lines,
    split_into_sentences,
)

# UI components
from taxonomica.ui import (
    NodeListDisplay,
    SortMode,
    clear_screen,
    display_node_list,
    format_rank,
    get_sorted_children,
    get_user_choice,
    index_to_label,
    label_to_index,
    wrap_text,
)

__all__ = [
    # Wikipedia DwC-A
    "DarwinCoreArchive",
    "Description",
    "Multimedia",
    "SpeciesProfile",
    "Taxon",
    "DwCATaxonomyNode",
    "DwCATaxonomyTree",
    "TypeSpecimen",
    "VernacularName",
    # Runtime taxonomy
    "MAJOR_RANKS",
    "RANK_PRIORITY",
    "TaxonNode",
    "TaxonomyTree",
    # GBIF Backbone (recommended)
    "GBIFBackbone",
    "GBIFMultimedia",
    "GBIFTaxon",
    "GBIFTaxonomyNode",
    "GBIFTaxonomyTree",
    "GBIFVernacularName",
    # ColDP
    "ColdPArchive",
    "ColdPMedia",
    "ColdPNameUsage",
    "ColdPProfile",
    "ColdPProfileRecord",
    "ColdPSQLiteStore",
    "ColdPSQLiteTaxon",
    "ColdPTaxonomyNode",
    "ColdPTaxonomyTree",
    "ColdPVernacularName",
    "CandidateMatch",
    "CandidateSpecies",
    "CandidateTreeBuildResult",
    "MajorRankPath",
    "build_candidate_tree",
    "build_sqlite_index",
    "default_sqlite_path",
    "extract_gbif_ids",
    "profile_archive",
    # Wikipedia descriptions
    "WikipediaData",
    "WikipediaDescription",
    "WikipediaSpecies",
    # Redaction
    "Redactor",
    "RedactionTerms",
    "build_redaction_terms_from_node",
    "build_redaction_terms_manual",
    # UI
    "NodeListDisplay",
    "SortMode",
    "clear_screen",
    "display_node_list",
    "format_rank",
    "get_sorted_children",
    "get_user_choice",
    "index_to_label",
    "label_to_index",
    "wrap_text",
    # Popularity
    "PopularityIndex",
    "PopularityMetrics",
    "RuntimeDescription",
    "RuntimeTaxonomyData",
    # Game
    "TaxonomicaGame",
    "get_rank_title",
    "get_seed_from_string",
    "select_playable_species",
    "split_into_lines",
    "split_into_sentences",
]
