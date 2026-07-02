from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from music_recommender.models import JsonDict
from music_recommender.recommender.data import MissingRecommenderDataError, read_dataset_records
from music_recommender.recommender.models import AudioFeatures, CatalogTrack, RecommenderCatalog


def load_recommender_catalog_from_run(
    data_root: Path | str,
    *,
    catalog_run_id: str,
    interaction_run_id: str | None = None,
) -> RecommenderCatalog:
    root = Path(data_root)
    tracks = _required_records(root / catalog_run_id / "silver" / "tracks")
    audio_features = _required_records(root / catalog_run_id / "silver" / "audio_features")
    lyrics_nlp = _optional_records(root / catalog_run_id / "silver" / "lyrics_nlp")
    interactions = (
        _optional_records(root / interaction_run_id / "gold" / "catalog_user_track_interactions")
        if interaction_run_id is not None
        else []
    )
    return catalog_from_records(
        tracks=tracks,
        audio_features=audio_features,
        lyrics_nlp=lyrics_nlp,
        interactions=interactions,
    )


def _required_records(path: Path) -> list[JsonDict]:
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


def _optional_records(path: Path) -> list[JsonDict]:
    if not path.exists():
        return []
    return read_dataset_records(path)


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
