from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from agents import Agent, Runner

from music_recommender.models import JsonDict
from music_recommender.recommender.models import MoodIntent

DEFAULT_INTENT_MODEL = "gpt-5-nano"


@dataclass(frozen=True)
class ParsedMoodIntent:
    label: str
    target_valence: float
    target_energy: float
    target_danceability: float
    allow_explicit: bool = True
    blocked_artist_names: tuple[str, ...] = ()
    rationale: str | None = None

    @classmethod
    def cheer_up_after_breakup(
        cls,
        *,
        allow_explicit: bool = True,
        blocked_artist_names: tuple[str, ...] = (),
        rationale: str | None = None,
    ) -> ParsedMoodIntent:
        domain_intent = MoodIntent.cheer_up_after_breakup(
            allow_explicit=allow_explicit,
            blocked_artist_names=blocked_artist_names,
        )
        return cls.from_domain(domain_intent, rationale=rationale)

    @classmethod
    def from_domain(cls, intent: MoodIntent, *, rationale: str | None = None) -> ParsedMoodIntent:
        return cls(
            label=intent.label,
            target_valence=intent.target_valence,
            target_energy=intent.target_energy,
            target_danceability=intent.target_danceability,
            allow_explicit=intent.allow_explicit,
            blocked_artist_names=intent.blocked_artist_names,
            rationale=rationale,
        )

    def to_domain(self) -> MoodIntent:
        return MoodIntent(
            label=self.label,
            target_valence=self.target_valence,
            target_energy=self.target_energy,
            target_danceability=self.target_danceability,
            allow_explicit=self.allow_explicit,
            blocked_artist_names=self.blocked_artist_names,
        )

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["blocked_artist_names"] = list(self.blocked_artist_names)
        return payload


IntentParser = Callable[[str], ParsedMoodIntent]


def build_intent_agent(*, model: str | None = None) -> Agent[Any]:
    return Agent(
        name="Music intent parser",
        model=model or DEFAULT_INTENT_MODEL,
        instructions=(
            "Convert the user's natural-language music request into a structured mood intent. "
            "Use numeric audio targets between 0 and 1. Do not recommend songs."
        ),
        output_type=ParsedMoodIntent,
    )


def parse_intent_with_agent(
    prompt: str,
    *,
    model: str | None = None,
    runner: Any = Runner,
) -> ParsedMoodIntent:
    result = runner.run_sync(build_intent_agent(model=model), prompt, max_turns=3)
    output = result.final_output
    if isinstance(output, ParsedMoodIntent):
        return output
    if isinstance(output, dict):
        return _intent_from_mapping(output)
    raise TypeError("Intent agent returned an unsupported output type.")


def parse_intent_deterministically(prompt: str) -> ParsedMoodIntent:
    normalized = prompt.casefold()
    allow_explicit = not any(term in normalized for term in ("clean", "no explicit", "family"))
    blocked_artists = _blocked_artist_names(normalized)
    if any(term in normalized for term in ("break up", "breakup", "broke up", "cheer me up")):
        return ParsedMoodIntent.cheer_up_after_breakup(
            allow_explicit=allow_explicit,
            blocked_artist_names=blocked_artists,
            rationale="Detected breakup or cheer-up language.",
        )
    if any(term in normalized for term in ("party", "dance", "workout", "hype")):
        return ParsedMoodIntent(
            label="high-energy",
            target_valence=0.78,
            target_energy=0.9,
            target_danceability=0.86,
            allow_explicit=allow_explicit,
            blocked_artist_names=blocked_artists,
            rationale="Detected high-energy language.",
        )
    if any(term in normalized for term in ("calm", "focus", "study", "relax")):
        return ParsedMoodIntent(
            label="calm-focus",
            target_valence=0.58,
            target_energy=0.34,
            target_danceability=0.42,
            allow_explicit=allow_explicit,
            blocked_artist_names=blocked_artists,
            rationale="Detected calm or focus language.",
        )
    return ParsedMoodIntent(
        label="balanced",
        target_valence=0.65,
        target_energy=0.62,
        target_danceability=0.62,
        allow_explicit=allow_explicit,
        blocked_artist_names=blocked_artists,
        rationale="Used balanced default intent.",
    )


def _intent_from_mapping(payload: dict[str, Any]) -> ParsedMoodIntent:
    blocked = payload.get("blocked_artist_names", ())
    blocked_names: tuple[str, ...]
    if isinstance(blocked, str):
        blocked_names = (blocked,)
    elif isinstance(blocked, list | tuple):
        blocked_names = tuple(str(item) for item in blocked if item is not None)
    else:
        blocked_names = ()
    return ParsedMoodIntent(
        label=str(payload["label"]),
        target_valence=float(payload["target_valence"]),
        target_energy=float(payload["target_energy"]),
        target_danceability=float(payload["target_danceability"]),
        allow_explicit=bool(payload.get("allow_explicit", True)),
        blocked_artist_names=blocked_names,
        rationale=str(payload["rationale"]) if payload.get("rationale") is not None else None,
    )


def _blocked_artist_names(prompt: str) -> tuple[str, ...]:
    marker = "avoid "
    if marker not in prompt:
        return ()
    suffix = prompt.split(marker, maxsplit=1)[1]
    first_clause = suffix.split(".", maxsplit=1)[0].split(",", maxsplit=1)[0]
    artist = first_clause.strip()
    return (artist,) if artist else ()
