from app.parsing_normalize import (
    extract_markdown_links,
    looks_like_name,
    normalize_percent_text,
    parse_decimal,
    parse_percent,
    strip_markdown_links,
)


def test_decimal_and_percent_normalization_is_locale_tolerant_but_strict() -> None:
    assert parse_decimal("4,25") == 4.25
    assert parse_decimal("rank 4.25") is None
    assert parse_decimal("rank 4.25", embedded=True) == 4.25
    assert parse_percent("51,7%") == 51.7
    assert normalize_percent_text("51,70") == "51.70%"
    assert normalize_percent_text("unknown") is None


def test_markdown_link_helpers_preserve_labels_and_urls() -> None:
    text = "Use [Tarecgosa](https://example.test/card) with [Poet](https://example.test/poet)."
    assert extract_markdown_links(text) == [
        ("Tarecgosa", "https://example.test/card"),
        ("Poet", "https://example.test/poet"),
    ]
    assert strip_markdown_links(text) == "Use Tarecgosa with Poet."


def test_name_heuristic_rejects_stats_descriptions_and_punctuation() -> None:
    options = {
        "skipped": {"Tier"},
        "description_prefixes": ("Discover",),
        "reject_terminal_punctuation": True,
    }
    assert looks_like_name("Tarecgosa", **options)
    assert not looks_like_name("51.7%", **options)
    assert not looks_like_name("Discover a Dragon", **options)
    assert not looks_like_name("Not a name.", **options)
