from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

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
AdventureMode = Literal["familiar", "balanced", "adventurous"]


class DiscoveryIntentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DiscoveryIntent:
    label: str
    tags: tuple[str, ...]
    adventure: AdventureMode
    allow_explicit: bool
    parser_version: str

    def to_dict(self) -> JsonDict:
        return {
            "label": self.label,
            "tags": list(self.tags),
            "adventure": self.adventure,
            "allow_explicit": self.allow_explicit,
            "parser_version": self.parser_version,
        }


PromptOnlyIntentParser = Callable[[str], dict[str, Any]]


class PolicySafeIntentParser:
    def __init__(
        self,
        *,
        llm_parser: PromptOnlyIntentParser | None = None,
        parser_version: str = "deterministic-intent-v1",
    ) -> None:
        normalized_version = parser_version.strip()
        if not normalized_version or len(normalized_version) > 100:
            raise ValueError("Intent parser version is invalid.")
        self.llm_parser = llm_parser
        self.parser_version = normalized_version

    def parse(
        self,
        prompt: str,
        *,
        adventure: AdventureMode,
        allow_explicit: bool,
    ) -> DiscoveryIntent:
        normalized_prompt = _product_prompt(prompt)
        if adventure not in {"familiar", "balanced", "adventurous"}:
            raise DiscoveryIntentValidationError("Adventure mode is invalid.")
        if self.llm_parser is None:
            label, tags = _deterministic_discovery_fields(normalized_prompt)
        else:
            label, tags = _validated_prompt_only_output(self.llm_parser(normalized_prompt))
        return DiscoveryIntent(
            label=label,
            tags=tags,
            adventure=adventure,
            allow_explicit=allow_explicit,
            parser_version=self.parser_version,
        )


def build_intent_agent(*, model: str | None = None) -> Any:
    from agents import Agent

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
    runner: Any | None = None,
) -> ParsedMoodIntent:
    if runner is None:
        from agents import Runner

        runner = Runner
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


def _deterministic_discovery_fields(prompt: str) -> tuple[str, tuple[str, ...]]:
    normalized = prompt.casefold()
    categories: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        (
            "high-energy",
            ("party", "dance", "workout", "running", "hype", "energetic"),
            ("dance", "electronic", "house"),
        ),
        (
            "calm-focus",
            ("calm", "focus", "study", "relax", "reading", "quiet"),
            ("ambient", "downtempo", "instrumental"),
        ),
        (
            "uplifting",
            ("break up", "breakup", "broke up", "cheer", "uplifting", "happy"),
            ("indie pop", "soul", "dance pop"),
        ),
        (
            "reflective",
            ("sad", "melancholy", "reflective", "rainy", "heartbreak"),
            ("dream pop", "slowcore", "indie rock"),
        ),
    )
    for label, terms, tags in categories:
        if any(term in normalized for term in terms):
            return label, tags
    genre_tags = tuple(
        genre
        for genre in (
            "ambient",
            "classical",
            "country",
            "electronic",
            "folk",
            "hip hop",
            "house",
            "indie rock",
            "jazz",
            "metal",
            "pop",
            "punk",
            "reggae",
            "r&b",
            "soul",
            "techno",
        )
        if genre in normalized
    )[:3]
    return ("genre-guided", genre_tags) if genre_tags else ("seed-led", ())


def _validated_prompt_only_output(payload: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    if not isinstance(payload, dict) or set(payload) != {"label", "tags"}:
        raise DiscoveryIntentValidationError(
            "Prompt parser output must contain only label and tags."
        )
    label_value = payload.get("label")
    tags_value = payload.get("tags")
    if not isinstance(label_value, str) or not isinstance(tags_value, list):
        raise DiscoveryIntentValidationError("Prompt parser output is invalid.")
    label = label_value.strip().casefold().replace(" ", "-")
    if (
        not 1 <= len(label) <= 50
        or not label.replace("-", "").isalnum()
        or label.startswith("-")
        or label.endswith("-")
    ):
        raise DiscoveryIntentValidationError("Prompt parser label is invalid.")
    tags: list[str] = []
    for value in tags_value:
        if not isinstance(value, str):
            raise DiscoveryIntentValidationError("Prompt parser tags are invalid.")
        tag = " ".join(value.split())
        if not 1 <= len(tag) <= 64:
            raise DiscoveryIntentValidationError("Prompt parser tags are invalid.")
        if tag.casefold() not in {existing.casefold() for existing in tags}:
            tags.append(tag)
        if len(tags) > 3:
            raise DiscoveryIntentValidationError("Prompt parser returned too many tags.")
    return label, tuple(tags)


def _product_prompt(value: str) -> str:
    normalized = " ".join(value.split())
    if not 2 <= len(normalized) <= 500 or any(ord(character) < 32 for character in normalized):
        raise DiscoveryIntentValidationError(
            "Discovery prompt must contain between 2 and 500 plain-text characters."
        )
    return normalized


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
