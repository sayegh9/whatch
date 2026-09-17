from pathlib import Path

from backend.app.importer import infer_media_type, normalize_title, parse_catalog, parse_year


SOURCE = Path(__file__).resolve().parents[2] / "bookmark_movies_tv_series_with_ratings.md"


def test_parse_complete_catalog() -> None:
    rows = parse_catalog(SOURCE)

    assert len(rows) == 324
    assert sum(row.imdb_id is not None for row in rows) == 312
    assert sum(row.imdb_id is None for row in rows) == 12


def test_year_parser_supports_series_ranges() -> None:
    assert parse_year("2024") == (2024, None, False)
    assert parse_year("2019–2024") == (2019, 2024, False)
    assert parse_year("2022–") == (2022, None, True)
    assert parse_year(None) == (None, None, False)


def test_normalized_title_is_search_and_group_friendly() -> None:
    assert normalize_title("Philip K. Dick's Electric Dreams") == (
        "philip k dick s electric dreams"
    )


def test_media_type_uses_group_and_url_evidence() -> None:
    rows = [row for row in parse_catalog(SOURCE) if row.imdb_id == "tt2937900"]

    assert len(rows) == 3
    assert infer_media_type(rows) == "tv"

