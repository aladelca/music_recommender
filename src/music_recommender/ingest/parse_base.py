from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from music_recommender.models import SeedArtist
from music_recommender.normalization import normalize_lookup_key

LABEL_PATTERN = re.compile(r"^(?:singer|band)\s*:\s*", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")


def load_aliases(path: Path | str) -> dict[str, str]:
    alias_path = Path(path)
    if not alias_path.exists():
        return {}
    loaded = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Alias file must contain a mapping: {alias_path}")
    return {normalize_lookup_key(str(key)): str(value).strip() for key, value in loaded.items()}


def clean_artist_token(token: str) -> str | None:
    cleaned = token.replace('"', "").replace("'", "'")
    cleaned = LABEL_PATTERN.sub("", cleaned.strip())
    cleaned = cleaned.strip().strip(".")
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned)
    return cleaned or None


def parse_seed_artists(
    path: Path | str,
    aliases_path: Path | str = "config/artist_aliases.yml",
) -> list[SeedArtist]:
    source_path = Path(path)
    lines = source_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []

    aliases = load_aliases(aliases_path)
    body = ",".join(lines[1:])
    artists: list[SeedArtist] = []
    seen: set[str] = set()

    for raw_token in body.split(","):
        original = clean_artist_token(raw_token)
        if not original:
            continue
        canonical = aliases.get(normalize_lookup_key(original), original)
        key = normalize_lookup_key(canonical)
        if key in seen:
            continue
        seen.add(key)
        artists.append(SeedArtist(original=original, name=canonical))

    return artists


def parse_alias_mapping(raw: dict[str, Any]) -> dict[str, str]:
    return {normalize_lookup_key(str(key)): str(value).strip() for key, value in raw.items()}
