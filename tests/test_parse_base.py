from pathlib import Path

from music_recommender.ingest.parse_base import parse_seed_artists


def test_parse_seed_artists_cleans_labels_aliases_and_duplicates(tmp_path: Path) -> None:
    seed_file = tmp_path / "base.md"
    seed_file.write_text(
        "\n".join(
            [
                "Favorite singer / band",
                "Billie Eilish",
                '"singer: Billie Eilish, Kali Uchis, Doja Cat',
                'band: Muse, Kalandra"',
                "kaliuchis, red hot chilli pepers, Edsheeran",
                "Víctor Jara.",
            ]
        ),
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.yml"
    aliases.write_text(
        "\n".join(
            [
                "kaliuchis: Kali Uchis",
                "red hot chilli pepers: Red Hot Chili Peppers",
                "edsheeran: Ed Sheeran",
            ]
        ),
        encoding="utf-8",
    )

    artists = parse_seed_artists(seed_file, aliases)

    assert [artist.name for artist in artists] == [
        "Billie Eilish",
        "Kali Uchis",
        "Doja Cat",
        "Muse",
        "Kalandra",
        "Red Hot Chili Peppers",
        "Ed Sheeran",
        "Víctor Jara",
    ]


def test_parse_seed_artists_returns_empty_for_empty_file(tmp_path: Path) -> None:
    seed_file = tmp_path / "empty.md"
    seed_file.write_text("", encoding="utf-8")

    assert parse_seed_artists(seed_file, tmp_path / "missing.yml") == []


def test_parse_seed_artists_dedupes_accent_insensitively(tmp_path: Path) -> None:
    seed_file = tmp_path / "base.md"
    seed_file.write_text("header\nVíctor Jara, Victor Jara\n", encoding="utf-8")

    artists = parse_seed_artists(seed_file, tmp_path / "missing.yml")

    assert [artist.name for artist in artists] == ["Víctor Jara"]
