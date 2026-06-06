from __future__ import annotations

import json
from pathlib import Path

from music_recommender.pipeline.network import (
    aggregate_linked_listens,
    aggregate_user_track_interactions,
    link_listens_to_catalog,
)
from music_recommender.sources.listenbrainz import (
    ListenBrainzDumpReader,
    spotify_track_id_from_value,
)


def test_listenbrainz_dump_reader_normalizes_records(tmp_path: Path) -> None:
    dump = tmp_path / "listens.jsonl"
    dump.write_text(
        json.dumps(
            {
                "user_name": "alice",
                "listened_at": 1710000000,
                "track_metadata": {
                    "artist_name": "Artist",
                    "track_name": "Song",
                    "release_name": "Album",
                    "additional_info": {
                        "recording_mbid": "mbid-1",
                        "isrc": ["ISRC1"],
                        "spotify_uri": "spotify:track:track123",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = list(ListenBrainzDumpReader().iter_listens(dump, run_id="run-1", user_hash_salt="s"))

    assert len(records) == 1
    assert records[0].artist_name == "Artist"
    assert records[0].track_name == "Song"
    assert records[0].isrc == "ISRC1"
    assert records[0].spotify_track_id == "track123"
    assert records[0].user_id_hash != "alice"


def test_aggregate_user_track_interactions_prefers_spotify_id(tmp_path: Path) -> None:
    dump = tmp_path / "listens.jsonl"
    line = {
        "user_name": "alice",
        "listened_at": 1710000000,
        "track_metadata": {
            "artist_name": "Artist",
            "track_name": "Song",
            "additional_info": {"spotify_id": "https://open.spotify.com/track/track123"},
        },
    }
    dump.write_text(json.dumps(line) + "\n" + json.dumps(line) + "\n", encoding="utf-8")
    records = list(ListenBrainzDumpReader().iter_listens(dump, run_id="run-1"))

    interactions = aggregate_user_track_interactions(records, "run-1")

    assert len(interactions) == 1
    assert interactions[0].item_id == "track123"
    assert interactions[0].item_id_type == "spotify_track_id"
    assert interactions[0].listen_count == 2


def test_spotify_track_id_from_value() -> None:
    assert spotify_track_id_from_value("spotify:track:abc123") == "abc123"
    assert spotify_track_id_from_value("https://open.spotify.com/track/abc123?si=x") == "abc123"
    assert spotify_track_id_from_value(None) is None


def test_link_listens_to_catalog_by_spotify_id_and_artist_track_name(tmp_path: Path) -> None:
    dump = tmp_path / "listens.jsonl"
    rows = [
        {
            "user_name": "alice",
            "listened_at": 1710000000,
            "track_metadata": {
                "artist_name": "Artist",
                "track_name": "Song",
                "additional_info": {"spotify_uri": "spotify:track:spotify-1"},
            },
        },
        {
            "user_name": "bob",
            "listened_at": 1710000001,
            "track_metadata": {"artist_name": "Other Artist", "track_name": "Other Song"},
        },
    ]
    dump.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    listens = list(ListenBrainzDumpReader().iter_listens(dump, run_id="run-1"))
    catalog = [
        {
            "spotify_track_id": "spotify-1",
            "isrc": None,
            "track_name": "Song",
            "primary_artist_name": "Artist",
        },
        {
            "spotify_track_id": "spotify-2",
            "isrc": None,
            "track_name": "Other Song",
            "primary_artist_name": "Other Artist",
        },
    ]

    linked = link_listens_to_catalog(listens, catalog)
    interactions = aggregate_linked_listens(linked, "run-1")

    assert [record.catalog_match_method for record in linked] == [
        "spotify_track_id",
        "artist_track_name",
    ]
    assert {record.item_id for record in interactions} == {"spotify-1", "spotify-2"}
    assert all(record.item_id_type == "catalog_spotify_track_id" for record in interactions)
