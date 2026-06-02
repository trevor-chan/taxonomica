from __future__ import annotations

from taxonomica.redaction import (
    Redactor,
    build_redaction_terms_from_node,
    build_redaction_terms_manual,
)
from taxonomica.taxonomy import TaxonNode


def test_plural_vernacular_name_adds_s_stripped_variant_from_node():
    species = TaxonNode(
        id="s-chipmunk",
        name="Tamias striatus",
        rank="species",
        vernacular_names=["Chipmunks"],
    )

    terms = build_redaction_terms_from_node(species)
    redactor = Redactor(terms)

    assert "Chipmunk" in terms.get_all_terms()
    assert redactor.redact("A chipmunk stores food.") == "A █████ stores food."


def test_plural_vernacular_phrase_adds_s_stripped_component():
    terms = build_redaction_terms_manual(
        {"species": "Tamias striatus"},
        {"species": ["Eastern chipmunks"]},
    )
    redactor = Redactor(terms)

    assert "chipmunk" in terms.get_all_terms()
    assert redactor.redact("The eastern chipmunk has cheek pouches.") == (
        "The █████ has cheek pouches."
    )
