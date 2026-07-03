from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from music_recommender.agent_cli import main


def test_agent_cli_recommend_outputs_ranked_json_from_local_catalog(
    capsys: Any,
    tmp_path: Path,
) -> None:
    write_table(
        tmp_path / "catalog-run" / "silver" / "tracks" / "dt=2026-05-22" / "part-000.parquet",
        [
            {
                "spotify_track_id": "sunny",
                "track_name": "Sunny Recovery",
                "artist_names": ["Dua Lipa"],
                "primary_artist_name": "Dua Lipa",
                "explicit": False,
                "popularity": 85,
                "spotify_url": "https://open.spotify.com/track/sunny",
            },
            {
                "spotify_track_id": "sad",
                "track_name": "Sad Ballad",
                "artist_names": ["Dua Lipa"],
                "primary_artist_name": "Dua Lipa",
                "explicit": False,
                "popularity": 90,
                "spotify_url": "https://open.spotify.com/track/sad",
            },
        ],
    )
    write_table(
        tmp_path
        / "catalog-run"
        / "silver"
        / "audio_features"
        / "dt=2026-05-22"
        / "part-000.parquet",
        [
            {
                "spotify_track_id": "sunny",
                "danceability": 0.86,
                "energy": 0.82,
                "valence": 0.93,
            },
            {
                "spotify_track_id": "sad",
                "danceability": 0.28,
                "energy": 0.22,
                "valence": 0.12,
            },
        ],
    )

    exit_code = main(
        [
            "recommend",
            "--prompt",
            "I just broke up with my girlfriend and I want songs to cheer me up",
            "--data-root",
            str(tmp_path),
            "--catalog-run-id",
            "catalog-run",
            "--limit",
            "1",
            "--liked-artist",
            "Dua Lipa",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["intent"]["label"] == "cheer-up"
    assert [item["track"]["id"] for item in payload["recommendations"]] == ["sunny"]


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)  # type: ignore[no-untyped-call]
