from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from music_recommender.models import JsonDict
from music_recommender.recommender.data import MissingRecommenderDataError, read_dataset_records
from music_recommender.recommender.models import AudioFeatures, CatalogTrack, RecommenderCatalog

DataMode = Literal["local", "s3"]
DatasetLocation = Path | str


def load_recommender_catalog_from_run(
    data_root: Path | str,
    *,
    catalog_run_id: str,
    interaction_run_id: str | None = None,
    data_mode: DataMode | None = None,
    s3_client: Any | None = None,
) -> RecommenderCatalog:
    mode = data_mode or ("s3" if _is_s3_location(data_root) else "local")
    tracks = _required_records(
        _dataset_location(
            data_root, run_id=catalog_run_id, layer="silver", dataset="tracks", mode=mode
        ),
        s3_client=s3_client,
    )
    audio_features = _required_records(
        _dataset_location(
            data_root,
            run_id=catalog_run_id,
            layer="silver",
            dataset="audio_features",
            mode=mode,
        ),
        s3_client=s3_client,
    )
    lyrics_nlp = _optional_records(
        _dataset_location(
            data_root,
            run_id=catalog_run_id,
            layer="silver",
            dataset="lyrics_nlp",
            mode=mode,
        ),
        s3_client=s3_client,
    )
    interactions = (
        _optional_records(
            _dataset_location(
                data_root,
                run_id=interaction_run_id,
                layer="gold",
                dataset="catalog_user_track_interactions",
                mode=mode,
            ),
            s3_client=s3_client,
        )
        if interaction_run_id is not None
        else []
    )
    return catalog_from_records(
        tracks=tracks,
        audio_features=audio_features,
        lyrics_nlp=lyrics_nlp,
        interactions=interactions,
    )


def _dataset_location(
    data_root: Path | str,
    *,
    run_id: str,
    layer: str,
    dataset: str,
    mode: DataMode,
) -> DatasetLocation:
    if mode == "s3":
        root = str(data_root).rstrip("/")
        return f"{root}/{layer}/{dataset}/run_id={run_id}"
    return Path(data_root) / run_id / layer / dataset


def _required_records(location: DatasetLocation, *, s3_client: Any | None = None) -> list[JsonDict]:
    if _is_s3_location(location):
        records = read_dataset_records(location, s3_client=s3_client)
        if not records:
            raise MissingRecommenderDataError(f"Missing required recommender dataset: {location}")
        return records

    path = Path(location)
    if not path.exists():
        raise MissingRecommenderDataError(f"Missing required recommender dataset: {path}")
    return read_dataset_records(path)


def catalog_from_records(
    *,
    tracks: Iterable[JsonDict],
    audio_features: Iterable[JsonDict] = (),
    lyrics_nlp: Iterable[JsonDict] = (),
    interactions: Iterable[JsonDict] = (),
) -> RecommenderCatalog:
    features_by_track_id = {
        feature.spotify_track_id: feature
        for feature in (
            _audio_features_from_record(record)
            for record in audio_features
            if _optional_str(record.get("spotify_track_id"))
        )
    }
    lyrics_by_track_id = {
        str(record["spotify_track_id"]): record
        for record in lyrics_nlp
        if _optional_str(record.get("spotify_track_id"))
    }
    interaction_summary = _interaction_summary(interactions)

    catalog_tracks: list[CatalogTrack] = []
    seen_track_ids: set[str] = set()
    for record in tracks:
        track_id = _optional_str(record.get("spotify_track_id"))
        if track_id is None or track_id in seen_track_ids:
            continue
        seen_track_ids.add(track_id)
        lyrics = lyrics_by_track_id.get(track_id, {})
        interaction_count, max_rating = interaction_summary.get(track_id, (0, None))
        catalog_tracks.append(
            CatalogTrack(
                id=track_id,
                name=_optional_str(record.get("track_name")) or track_id,
                artist_names=_string_tuple(record.get("artist_names")),
                primary_artist_name=_optional_str(record.get("primary_artist_name")),
                explicit=bool(record.get("explicit") or False),
                popularity=_optional_int(record.get("popularity")),
                spotify_url=_optional_str(record.get("spotify_url")),
                seed_artist=_optional_str(record.get("seed_artist")),
                audio_features=features_by_track_id.get(track_id),
                lyrics_sentiment_label=_optional_str(lyrics.get("sentiment_label")),
                lyrics_positive_score=_optional_float(lyrics.get("positive_score")),
                lyrics_negative_score=_optional_float(lyrics.get("negative_score")),
                lyrics_neutral_score=_optional_float(lyrics.get("neutral_score")),
                interaction_count=interaction_count,
                max_implicit_rating=max_rating,
            )
        )
    return RecommenderCatalog(tracks=tuple(catalog_tracks))


def _optional_records(location: DatasetLocation, *, s3_client: Any | None = None) -> list[JsonDict]:
    if _is_s3_location(location):
        return read_dataset_records(location, s3_client=s3_client)
    path = Path(location)
    if not path.exists():
        return []
    return read_dataset_records(path)


def _is_s3_location(location: Path | str) -> bool:
    return str(location).startswith("s3://")


def _audio_features_from_record(record: JsonDict) -> AudioFeatures:
    return AudioFeatures(
        spotify_track_id=str(record["spotify_track_id"]),
        danceability=_optional_float(record.get("danceability")),
        energy=_optional_float(record.get("energy")),
        valence=_optional_float(record.get("valence")),
        acousticness=_optional_float(record.get("acousticness")),
        instrumentalness=_optional_float(record.get("instrumentalness")),
        tempo=_optional_float(record.get("tempo")),
    )


def _interaction_summary(records: Iterable[JsonDict]) -> dict[str, tuple[int, float | None]]:
    grouped: dict[str, list[float]] = {}
    for record in records:
        track_id = _optional_str(record.get("item_id"))
        if track_id is None:
            continue
        grouped.setdefault(track_id, []).append(
            _optional_float(record.get("implicit_rating")) or 0.0
        )
    return {
        track_id: (len(ratings), max(ratings) if ratings else None)
        for track_id, ratings in grouped.items()
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
