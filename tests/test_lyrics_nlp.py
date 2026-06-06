from __future__ import annotations

from music_recommender.models import LyricsRecord
from music_recommender.nlp.language import LanguageDetectionResult
from music_recommender.nlp.lyrics import LyricsNlpProcessor
from music_recommender.nlp.sentiment import (
    SentimentResult,
    aggregate_sentiment_outputs,
    chunk_text,
)


class FakeLanguageDetector:
    def detect(self, text: str | None) -> LanguageDetectionResult:
        if not text:
            return LanguageDetectionResult("unknown", None, "fake-language")
        return LanguageDetectionResult("es", 0.91, "fake-language")


class FakeSentimentAnalyzer:
    def analyze(self, text: str | None) -> SentimentResult:
        if not text:
            return SentimentResult(
                label="not_available",
                score=None,
                negative_score=None,
                neutral_score=None,
                positive_score=None,
                model_name="fake-sentiment",
                chunk_count=0,
            )
        return SentimentResult(
            label="positive",
            score=0.8,
            negative_score=0.1,
            neutral_score=0.1,
            positive_score=0.8,
            model_name="fake-sentiment",
            chunk_count=1,
        )


def make_lyrics(text: str | None) -> LyricsRecord:
    return LyricsRecord(
        spotify_track_id="track-1",
        track_name="Song",
        artist_name="Artist",
        album_name="Album",
        duration_ms=120000,
        lyrics_source="lrclib",
        match_status="hit" if text else "miss",
        plain_lyrics=text,
    )


def test_lyrics_nlp_enriches_language_and_sentiment() -> None:
    processor = LyricsNlpProcessor(
        language_detector=FakeLanguageDetector(),
        sentiment_analyzer=FakeSentimentAnalyzer(),
    )

    record = processor.enrich(make_lyrics("hola mundo"), "run-1")

    assert record.language == "es"
    assert record.language_confidence == 0.91
    assert record.sentiment_label == "positive"
    assert record.positive_score == 0.8
    assert record.source_run_id == "run-1"


def test_missing_lyrics_returns_not_available() -> None:
    processor = LyricsNlpProcessor(
        language_detector=FakeLanguageDetector(),
        sentiment_analyzer=FakeSentimentAnalyzer(),
    )

    record = processor.enrich(make_lyrics(None), "run-1")

    assert record.language == "unknown"
    assert record.sentiment_label == "not_available"


def test_chunk_text_and_aggregate_sentiment_outputs() -> None:
    chunks = chunk_text("one two three four", max_chars=8)
    outputs = [
        [
            {"label": "negative", "score": 0.2},
            {"label": "neutral", "score": 0.3},
            {"label": "positive", "score": 0.5},
        ],
        [
            {"label": "negative", "score": 0.6},
            {"label": "neutral", "score": 0.3},
            {"label": "positive", "score": 0.1},
        ],
    ]

    scores = aggregate_sentiment_outputs(outputs, chunks)

    assert chunks == ["one two", "three", "four"]
    assert set(scores) == {"negative", "neutral", "positive"}
