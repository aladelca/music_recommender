from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

LOGGER = logging.getLogger(__name__)
FASTTEXT_LID_176_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"


@dataclass(frozen=True)
class LanguageDetectionResult:
    language: str
    confidence: float | None
    model_name: str


class FastTextModel(Protocol):
    def predict(self, text: str, k: int = 1) -> tuple[list[str], list[float]]: ...


class FastTextLanguageDetector:
    def __init__(
        self,
        *,
        model_path: Path | None = None,
        model_name: str = "fasttext-lid-176",
        download_if_missing: bool = True,
    ) -> None:
        self.model_name = model_name
        self.model_path = model_path or default_model_path()
        self.download_if_missing = download_if_missing
        self._model: FastTextModel | None = None

    def detect(self, text: str | None) -> LanguageDetectionResult:
        cleaned = clean_text(text)
        if not cleaned:
            return LanguageDetectionResult("unknown", None, self.model_name)

        model = self._load_model()
        labels, scores = model.predict(cleaned.replace("\n", " "), k=1)
        if not labels:
            return LanguageDetectionResult("unknown", None, self.model_name)

        language = str(labels[0]).replace("__label__", "")
        confidence = float(scores[0]) if scores else None
        return LanguageDetectionResult(language, confidence, self.model_name)

    def _load_model(self) -> FastTextModel:
        if self._model is not None:
            return self._model

        if not self.model_path.exists():
            if not self.download_if_missing:
                raise FileNotFoundError(
                    f"fastText language model not found at {self.model_path}. "
                    "Set LYRICS_LANGUAGE_MODEL_PATH or allow download."
                )
            download_fasttext_model(self.model_path)

        try:
            import fasttext
        except ImportError as error:
            raise RuntimeError(
                "fasttext-wheel is required for lyrics language detection. "
                "Install NLP extras with: uv sync --extra nlp"
            ) from error

        LOGGER.info("Loading fastText language model from %s", self.model_path)
        self._model = fasttext.load_model(str(self.model_path))
        return self._model


def default_model_path() -> Path:
    return Path.home() / ".cache" / "music-recommender" / "models" / "lid.176.ftz"


def download_fasttext_model(target: Path) -> None:
    LOGGER.info("Downloading fastText language model to %s", target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream(
        "GET", FASTTEXT_LID_176_URL, follow_redirects=True, timeout=120.0
    ) as response:
        response.raise_for_status()
        with target.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)


def clean_text(text: str | None) -> str:
    if text is None:
        return ""
    return " ".join(text.strip().split())
