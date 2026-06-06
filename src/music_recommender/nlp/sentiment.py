from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_SENTIMENT_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual"
SENTIMENT_LABELS = ("negative", "neutral", "positive")


@dataclass(frozen=True)
class SentimentResult:
    label: str
    score: float | None
    negative_score: float | None
    neutral_score: float | None
    positive_score: float | None
    model_name: str
    chunk_count: int


class TransformersSentimentAnalyzer:
    def __init__(
        self,
        *,
        model_name: str = DEFAULT_SENTIMENT_MODEL,
        batch_size: int = 8,
        max_chunk_chars: int = 1800,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_chunk_chars = max_chunk_chars
        self._pipeline: Any | None = None

    def analyze(self, text: str | None) -> SentimentResult:
        chunks = chunk_text(text, max_chars=self.max_chunk_chars)
        if not chunks:
            return SentimentResult(
                label="not_available",
                score=None,
                negative_score=None,
                neutral_score=None,
                positive_score=None,
                model_name=self.model_name,
                chunk_count=0,
            )

        classifier = self._load_pipeline()
        outputs = classifier(chunks, top_k=None, batch_size=self.batch_size, truncation=True)
        scores = aggregate_sentiment_outputs(outputs, chunks)
        label, score = max(scores.items(), key=lambda item: item[1])
        return SentimentResult(
            label=label,
            score=score,
            negative_score=scores["negative"],
            neutral_score=scores["neutral"],
            positive_score=scores["positive"],
            model_name=self.model_name,
            chunk_count=len(chunks),
        )

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        try:
            from transformers import pipeline
        except ImportError as error:
            raise RuntimeError(
                "transformers and torch are required for lyrics sentiment. "
                "Install NLP extras with: uv sync --extra nlp"
            ) from error

        self._pipeline = pipeline("text-classification", model=self.model_name)
        return self._pipeline


def chunk_text(text: str | None, *, max_chars: int) -> list[str]:
    if text is None:
        return []
    words = text.strip().split()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        next_length = current_length + len(word) + (1 if current else 0)
        if current and next_length > max_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_length = len(word)
            continue
        current.append(word)
        current_length = next_length
    if current:
        chunks.append(" ".join(current))
    return chunks


def aggregate_sentiment_outputs(outputs: Any, chunks: list[str]) -> dict[str, float]:
    totals = {label: 0.0 for label in SENTIMENT_LABELS}
    total_weight = 0.0
    normalized_outputs = outputs if isinstance(outputs, list) else [outputs]
    for output, chunk in zip(normalized_outputs, chunks, strict=False):
        weight = max(float(len(chunk)), 1.0)
        total_weight += weight
        for item in _as_label_scores(output):
            label = normalize_sentiment_label(item.get("label"))
            if label in totals:
                totals[label] += float(item.get("score") or 0.0) * weight

    if total_weight == 0:
        return totals
    return {label: value / total_weight for label, value in totals.items()}


def _as_label_scores(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, list):
        return [item for item in output if isinstance(item, dict)]
    if isinstance(output, dict):
        return [output]
    return []


def normalize_sentiment_label(label: Any) -> str:
    normalized = str(label or "").lower()
    label_map = {
        "label_0": "negative",
        "label_1": "neutral",
        "label_2": "positive",
        "negative": "negative",
        "neutral": "neutral",
        "positive": "positive",
        "neg": "negative",
        "neu": "neutral",
        "pos": "positive",
    }
    return label_map.get(normalized, normalized)
