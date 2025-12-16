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
from taxonomica.tree import TaxonomyNode, TaxonomyTree

# GBIF Backbone parser (complete hierarchies) - recommended
from taxonomica.gbif_backbone import (
    GBIFBackbone,
    GBIFMultimedia,
    GBIFTaxon,
    GBIFVernacularName,
)
from taxonomica.gbif_tree import GBIFTaxonomyTree
from taxonomica.gbif_tree import TaxonomyNode as GBIFTaxonomyNode

__all__ = [
    # Wikipedia DwC-A
    "DarwinCoreArchive",
    "Description",
    "Multimedia",
    "SpeciesProfile",
    "Taxon",
    "TaxonomyNode",
    "TaxonomyTree",
    "TypeSpecimen",
    "VernacularName",
    # GBIF Backbone (recommended)
    "GBIFBackbone",
    "GBIFMultimedia",
    "GBIFTaxon",
    "GBIFTaxonomyNode",
    "GBIFTaxonomyTree",
    "GBIFVernacularName",
]

