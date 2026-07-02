from __future__ import annotations

import base64
import urllib.parse

import httpx
import pytest

from music_recommender.sources.http import ApiHttpClient
from music_recommender.sources.spotify_user import (
    SpotifyScopeError,
    SpotifyUserClient,
    build_authorization_url,
    missing_required_scopes,
    spotify_track_uri,
)


def test_build_authorization_url_includes_required_query_parameters() -> None:
    url = build_authorization_url(
        client_id="client",
        redirect_uri="http://127.0.0.1:8080/callback",
        scopes=("user-top-read", "playlist-modify-private"),
        state="state-1",
    )

    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.spotify.com"
    assert parsed.path == "/authorize"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["client"]
    assert params["redirect_uri"] == ["http://127.0.0.1:8080/callback"]
    assert params["scope"] == ["user-top-read playlist-modify-private"]
    assert params["state"] == ["state-1"]


def test_refresh_access_token_uses_refresh_grant_and_basic_auth() -> None:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "access_token": "access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "user-top-read playlist-modify-private",
            },
            request=request,
        )

    client = build_client(auth_transport=httpx.MockTransport(handler))

    token = client.refresh_access_token(
        required_scopes=("user-top-read", "playlist-modify-private")
    )

    assert token.access_token == "access"
    assert token.token_type == "Bearer"
    assert token.expires_in == 3600
    assert captured_request is not None
    assert captured_request.url.path == "/api/token"
    expected_basic = base64.b64encode(b"client:secret").decode("ascii")
    assert captured_request.headers["authorization"] == f"Basic {expected_basic}"
    assert captured_request.headers["content-type"] == "application/x-www-form-urlencoded"
    form = urllib.parse.parse_qs(captured_request.content.decode("utf-8"))
    assert form == {"grant_type": ["refresh_token"], "refresh_token": ["refresh"]}


def test_refresh_access_token_rejects_missing_required_scopes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access",
                "expires_in": 3600,
                "scope": "user-top-read",
            },
            request=request,
        )

    client = build_client(auth_transport=httpx.MockTransport(handler))

    with pytest.raises(SpotifyScopeError, match="playlist-modify-private"):
        client.refresh_access_token(required_scopes=("user-top-read", "playlist-modify-private"))


def test_user_profile_and_playlist_calls_use_bearer_token() -> None:
    requests: list[httpx.Request] = []

    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "access", "expires_in": 3600},
            request=request,
        )

    def api_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer access"
        if request.url.path == "/v1/me":
            return httpx.Response(200, json={"id": "12175364859"}, request=request)
        if request.url.path == "/v1/me/top/tracks":
            return httpx.Response(200, json={"items": [{"id": "track-1"}]}, request=request)
        if request.url.path == "/v1/me/tracks":
            return httpx.Response(
                200, json={"items": [{"track": {"id": "saved-1"}}]}, request=request
            )
        if request.url.path == "/v1/users/12175364859/playlists":
            return httpx.Response(
                201,
                json={
                    "id": "playlist-1",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-1"},
                },
                request=request,
            )
        if request.url.path == "/v1/playlists/playlist-1/tracks":
            return httpx.Response(201, json={"snapshot_id": "snapshot-1"}, request=request)
        return httpx.Response(404, request=request)

    client = build_client(
        auth_transport=httpx.MockTransport(auth_handler),
        api_transport=httpx.MockTransport(api_handler),
    )

    assert client.get_current_user_profile()["id"] == "12175364859"
    assert client.get_top_items("tracks", limit=1)["items"][0]["id"] == "track-1"
    assert client.get_saved_tracks(limit=1)["items"][0]["track"]["id"] == "saved-1"
    playlist = client.create_playlist(
        "12175364859",
        name="Demo",
        description="Class demo",
        public=False,
    )
    add_result = client.add_playlist_items("playlist-1", ["track-1", "spotify:track:track-2"])

    assert playlist["id"] == "playlist-1"
    assert add_result["snapshot_id"] == "snapshot-1"
    add_request = requests[-1]
    assert add_request.read() == b'{"uris":["spotify:track:track-1","spotify:track:track-2"]}'


def test_scope_and_uri_helpers() -> None:
    assert missing_required_scopes(
        "user-top-read playlist-modify-private",
        ("user-top-read", "user-library-read"),
    ) == ["user-library-read"]
    assert spotify_track_uri("track-1") == "spotify:track:track-1"
    assert spotify_track_uri("spotify:track:track-2") == "spotify:track:track-2"


def build_client(
    *,
    auth_transport: httpx.MockTransport,
    api_transport: httpx.MockTransport | None = None,
) -> SpotifyUserClient:
    return SpotifyUserClient(
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
        auth_http=ApiHttpClient(
            client=httpx.Client(
                transport=auth_transport,
                base_url="https://accounts.spotify.com",
            )
        ),
        api_http=ApiHttpClient(
            client=httpx.Client(
                transport=api_transport
                or httpx.MockTransport(lambda request: httpx.Response(404, request=request)),
                base_url="https://api.spotify.com/v1",
            )
        ),
    )
