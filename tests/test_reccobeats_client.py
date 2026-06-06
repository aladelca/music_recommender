from __future__ import annotations

import httpx

from music_recommender.sources.http import ApiHttpClient
from music_recommender.sources.reccobeats import ReccoBeatsClient


def test_reccobeats_batch_audio_features_partial_coverage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio-features"
        assert request.url.params["ids"] == "track-1,track-2"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "href": "https://open.spotify.com/track/track-1",
                        "isrc": "ISRC1",
                        "danceability": 0.7,
                        "energy": 0.8,
                    }
                ]
            },
            request=request,
        )

    client = ReccoBeatsClient(
        http=ApiHttpClient(
            client=httpx.Client(
                transport=httpx.MockTransport(handler),
                base_url="https://api.reccobeats.com/v1",
            )
        )
    )

    records = client.get_audio_features(["track-1", "track-2"], "now")

    assert [record.status for record in records] == ["hit", "miss"]
    assert records[0].source == "reccobeats"
    assert records[0].isrc == "ISRC1"
    assert records[0].raw is not None
    assert records[0].raw["danceability"] == 0.7


def test_reccobeats_unavailable_is_non_fatal() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request))
    client = ReccoBeatsClient(
        http=ApiHttpClient(
            client=httpx.Client(transport=transport, base_url="https://api.reccobeats.com/v1")
        )
    )

    records = client.get_audio_features(["track-1"], "now")

    assert records[0].status == "unavailable"
    assert records[0].error_code == 403
