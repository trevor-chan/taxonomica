from build_tree.extract_wikipedia_descriptions import (
    clean_wikitext_description,
    clean_wikitext_lead,
)


def test_clean_wikitext_description_keeps_prose_after_lead():
    wikitext = """
{{Short description|example species}}
{{Speciesbox|image=Example.jpg}}

'''Example frog''' is a small frog from cloud forests.

==Description==
Adults have blue legs and yellow spots. They call during rainstorms.

==Distribution==
It lives near mountain streams.

==References==
* This citation should not enter gameplay text.
"""

    description = clean_wikitext_description(wikitext, max_chars=1500)

    assert "small frog" in description
    assert "blue legs" in description
    assert "mountain streams" in description
    assert "References" not in description
    assert "citation should not enter" not in description


def test_clean_wikitext_description_avoids_tiny_trailing_fragments():
    wikitext = """
'''Example frog''' is a small frog from cloud forests.

==Description==
Adults have blue legs and yellow spots. They call during rainstorms.

==Habitat==
This sentence would only have a tiny amount of room left after the previous
paragraphs, so it should be skipped instead of stored as a fragment.
"""

    description = clean_wikitext_description(wikitext, max_chars=130)

    assert len(description) <= 130
    assert not description.endswith("T")
    assert "tiny amount of room" not in description


def test_clean_wikitext_lead_keeps_legacy_paragraph_limit():
    wikitext = """
'''Example frog''' is a small frog.

It has a useful second paragraph.

A third paragraph should be omitted.
"""

    description = clean_wikitext_lead(wikitext, paragraphs=2)

    assert "small frog" in description
    assert "second paragraph" in description
    assert "third paragraph" not in description
