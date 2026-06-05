from __future__ import annotations

from taxonomica.candidate_tree import _path_from_gbif_row


def test_path_from_gbif_row_infers_bony_fish_class_from_order():
    path = _path_from_gbif_row(
        _gbif_species_row(
            order="Cypriniformes",
            family="Cyprinidae",
            genus="Danio",
            canonical_name="Danio rerio",
            scientific_name="Danio rerio (Hamilton, 1822)",
        )
    )

    assert path is not None
    assert path.class_name == "Actinopterygii"
    assert path.order == "Cypriniformes"
    assert path.species == "Danio rerio"


def test_path_from_gbif_row_does_not_infer_non_fish_chordate_order():
    path = _path_from_gbif_row(
        _gbif_species_row(
            order="Copelata",
            family="Oikopleuridae",
            genus="Oikopleura",
            canonical_name="Oikopleura dioica",
            scientific_name="Oikopleura dioica Fol, 1872",
        )
    )

    assert path is None


def test_path_from_gbif_row_keeps_existing_class():
    path = _path_from_gbif_row(
        _gbif_species_row(
            class_name="Elasmobranchii",
            order="Carcharhiniformes",
            family="Carcharhinidae",
            genus="Carcharhinus",
            canonical_name="Carcharhinus leucas",
            scientific_name="Carcharhinus leucas (Valenciennes, 1839)",
        )
    )

    assert path is not None
    assert path.class_name == "Elasmobranchii"


def _gbif_species_row(
    *,
    class_name: str = "",
    order: str,
    family: str,
    genus: str,
    canonical_name: str,
    scientific_name: str,
) -> dict[str, str]:
    return {
        "taxonomicStatus": "accepted",
        "taxonRank": "species",
        "kingdom": "Animalia",
        "phylum": "Chordata",
        "class": class_name,
        "order": order,
        "family": family,
        "genus": genus,
        "canonicalName": canonical_name,
        "scientificName": scientific_name,
    }
