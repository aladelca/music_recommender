from __future__ import annotations

from pathlib import Path
from typing import Protocol

from music_recommender.models import LyricsNlpRecord, LyricsRecord
from music_recommender.nlp.language import FastTextLanguageDetector, LanguageDetectionResult
from music_recommender.nlp.sentiment import (
    DEFAULT_SENTIMENT_MODEL,
    SentimentResult,
    TransformersSentimentAnalyzer,
)


class LanguageDetector(Protocol):
    def detect(self, text: str | None) -> LanguageDetectionResult: ...


class SentimentAnalyzer(Protocol):
    def analyze(self, text: str | None) -> SentimentResult: ...


class LyricsNlpProcessor:
    def __init__(
        self,
        *,
        language_detector: LanguageDetector,
        sentiment_analyzer: SentimentAnalyzer,
    ) -> None:
        self.language_detector = language_detector
        self.sentiment_analyzer = sentiment_analyzer

    @classmethod
    def default(
        cls,
        *,
        language_model: str = "fasttext-lid-176",
        language_model_path: Path | None = None,
        sentiment_model: str = DEFAULT_SENTIMENT_MODEL,
        batch_size: int = 8,
    ) -> LyricsNlpProcessor:
        if language_model != "fasttext-lid-176":
            raise ValueError(
                "Only fasttext-lid-176 is currently supported for lyric language detection."
            )
        return cls(
            language_detector=FastTextLanguageDetector(
                model_path=language_model_path,
                model_name=language_model,
            ),
            sentiment_analyzer=TransformersSentimentAnalyzer(
                model_name=sentiment_model,
                batch_size=batch_size,
            ),
        )

    def enrich(self, lyrics: LyricsRecord, run_id: str) -> LyricsNlpRecord:
        text = lyrics.plain_lyrics or lyrics.synced_lyrics
        language = self.language_detector.detect(text)
        sentiment = self.sentiment_analyzer.analyze(text)
        return LyricsNlpRecord(
            spotify_track_id=lyrics.spotify_track_id,
            lyrics_source=lyrics.lyrics_source,
            language=language.language,
            language_confidence=language.confidence,
            language_model=language.model_name,
            sentiment_label=sentiment.label,
            sentiment_score=sentiment.score,
            negative_score=sentiment.negative_score,
            neutral_score=sentiment.neutral_score,
            positive_score=sentiment.positive_score,
            sentiment_model=sentiment.model_name,
            chunk_count=sentiment.chunk_count,
            source_run_id=run_id,
        )
