from __future__ import annotations

import base64
import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from music_recommender.models import JsonDict
from music_recommender.sources.http import ApiHttpClient
from music_recommender.sources.spotify import API_BASE_URL, AUTH_BASE_URL

TopItemType = Literal["artists", "tracks"]
TopTimeRange = Literal["short_term", "medium_term", "long_term"]


class SpotifyScopeError(ValueError):
    pass


@dataclass(frozen=True)
class SpotifyAccessToken:
    access_token: str
    token_type: str
    expires_in: int
    scope: str
    refresh_token: str | None = None

    @classmethod
    def from_payload(cls, payload: JsonDict) -> SpotifyAccessToken:
        return cls(
            access_token=str(payload["access_token"]),
            token_type=str(payload.get("token_type", "Bearer")),
            expires_in=int(payload.get("expires_in", 3600)),
            scope=str(payload.get("scope", "")),
            refresh_token=_optional_str(payload.get("refresh_token")),
        )


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    state: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    if state:
        params["state"] = state
    return f"{AUTH_BASE_URL}/authorize?{urllib.parse.urlencode(params)}"


def missing_required_scopes(granted_scope: str, required_scopes: tuple[str, ...]) -> list[str]:
    granted = set(granted_scope.split())
    return [scope for scope in required_scopes if scope not in granted]


def spotify_track_uri(track_id_or_uri: str) -> str:
    if track_id_or_uri.startswith("spotify:track:"):
        return track_id_or_uri
    return f"spotify:track:{track_id_or_uri}"


class SpotifyUserClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str | None = None,
        auth_http: ApiHttpClient | None = None,
        api_http: ApiHttpClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.auth_http = auth_http or ApiHttpClient(base_url=AUTH_BASE_URL)
        self.api_http = api_http or ApiHttpClient(base_url=API_BASE_URL)
        self._access_token: str | None = None
        self._expires_at = 0.0

    def close(self) -> None:
        self.auth_http.close()
        self.api_http.close()

    def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        required_scopes: tuple[str, ...] = (),
    ) -> SpotifyAccessToken:
        payload = self._request_token(
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }
        )
        token = SpotifyAccessToken.from_payload(payload)
        self._store_token(token)
        self._require_scopes(token, required_scopes)
        return token

    def refresh_access_token(
        self,
        *,
        required_scopes: tuple[str, ...] = (),
    ) -> SpotifyAccessToken:
        if not self.refresh_token:
            raise ValueError("SPOTIFY_USER_REFRESH_TOKEN is required to refresh a user token.")
        payload = self._request_token(
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        )
        token = SpotifyAccessToken.from_payload(payload)
        self._store_token(token)
        self._require_scopes(token, required_scopes)
        return token

    def get_access_token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 30:
            return self._access_token
        return self.refresh_access_token().access_token

    def get_current_user_profile(self) -> JsonDict:
        return self._get("/me")

    def get_top_items(
        self,
        item_type: TopItemType,
        *,
        limit: int = 20,
        offset: int = 0,
        time_range: TopTimeRange = "medium_term",
    ) -> JsonDict:
        return self._get(
            f"/me/top/{item_type}",
            params={"limit": limit, "offset": offset, "time_range": time_range},
        )

    def get_saved_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> JsonDict:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if market:
            params["market"] = market
        return self._get("/me/tracks", params=params)

    def iter_saved_tracks(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
    ) -> Iterator[JsonDict]:
        params: dict[str, str | int] = {}
        if market:
            params["market"] = market
        yield from self._iter_paged_items(
            "/me/tracks",
            limit_total=limit_total,
            page_size=page_size,
            params=params,
        )

    def iter_top_items(
        self,
        item_type: TopItemType,
        *,
        limit_total: int,
        time_range: TopTimeRange = "medium_term",
        page_size: int = 50,
    ) -> Iterator[JsonDict]:
        yield from self._iter_paged_items(
            f"/me/top/{item_type}",
            limit_total=limit_total,
            page_size=page_size,
            params={"time_range": time_range},
        )

    def get_current_user_playlists(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> JsonDict:
        return self._get("/me/playlists", params={"limit": limit, "offset": offset})

    def iter_current_user_playlists(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
    ) -> Iterator[JsonDict]:
        yield from self._iter_paged_items(
            "/me/playlists",
            limit_total=limit_total,
            page_size=page_size,
            params={},
        )

    def get_playlist_items(
        self,
        playlist_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
        fields: str | None = None,
    ) -> JsonDict:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if market:
            params["market"] = market
        if fields:
            params["fields"] = fields
        return self._get(f"/playlists/{playlist_id}/items", params=params)

    def iter_playlist_items(
        self,
        playlist_id: str,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
        fields: str | None = None,
    ) -> Iterator[JsonDict]:
        params: dict[str, str | int] = {}
        if market:
            params["market"] = market
        if fields:
            params["fields"] = fields
        yield from self._iter_paged_items(
            f"/playlists/{playlist_id}/items",
            limit_total=limit_total,
            page_size=page_size,
            params=params,
        )

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> JsonDict:
        params: dict[str, int] = {"limit": limit}
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        return self._get("/me/player/recently-played", params=params)

    def create_playlist(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> JsonDict:
        return self._post(
            f"/users/{user_id}/playlists",
            json={"name": name, "description": description, "public": public},
            expected_statuses=(200, 201),
        )

    def add_playlist_items(self, playlist_id: str, track_ids_or_uris: list[str]) -> JsonDict:
        if not track_ids_or_uris:
            raise ValueError("At least one Spotify track ID or URI is required.")
        if len(track_ids_or_uris) > 100:
            raise ValueError("Spotify accepts at most 100 playlist items per request.")
        uris = [spotify_track_uri(track_id_or_uri) for track_id_or_uri in track_ids_or_uris]
        return self._post(
            f"/playlists/{playlist_id}/tracks",
            json={"uris": uris},
            expected_statuses=(200, 201),
        )

    def _request_token(self, *, data: dict[str, str]) -> JsonDict:
        response = self.auth_http.post(
            "/api/token",
            headers={
                "Authorization": f"Basic {_basic_auth_value(self.client_id, self.client_secret)}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
        )
        return _json_object(response.json(), "/api/token")

    def _store_token(self, token: SpotifyAccessToken) -> None:
        self._access_token = token.access_token
        self._expires_at = time.time() + token.expires_in
        if token.refresh_token:
            self.refresh_token = token.refresh_token

    def _require_scopes(
        self,
        token: SpotifyAccessToken,
        required_scopes: tuple[str, ...],
    ) -> None:
        missing = missing_required_scopes(token.scope, required_scopes)
        if missing:
            raise SpotifyScopeError(
                "Spotify user token is missing required scopes: " + ", ".join(missing)
            )

    def _get(self, path: str, **kwargs: Any) -> JsonDict:
        response = self.api_http.get(
            path,
            headers={"Authorization": f"Bearer {self.get_access_token()}"},
            **kwargs,
        )
        return _json_object(response.json(), path)

    def _post(self, path: str, **kwargs: Any) -> JsonDict:
        response = self.api_http.post(
            path,
            headers={"Authorization": f"Bearer {self.get_access_token()}"},
            **kwargs,
        )
        return _json_object(response.json(), path)

    def _iter_paged_items(
        self,
        path: str,
        *,
        limit_total: int,
        page_size: int,
        params: dict[str, str | int],
    ) -> Iterator[JsonDict]:
        if limit_total <= 0:
            return
        offset = 0
        emitted = 0
        bounded_page_size = _bounded_page_size(page_size)
        while emitted < limit_total:
            request_limit = min(bounded_page_size, limit_total - emitted)
            page_params = {**params, "limit": request_limit, "offset": offset}
            payload = self._get(path, params=page_params)
            items = payload.get("items", [])
            if not isinstance(items, list) or not items:
                return
            yielded_this_page = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                yield item
                emitted += 1
                yielded_this_page += 1
                if emitted >= limit_total:
                    return
            if yielded_this_page == 0 or len(items) < request_limit:
                return
            offset += len(items)


def _json_object(payload: Any, path: str) -> JsonDict:
    if not isinstance(payload, dict):
        raise ValueError(f"Spotify response must be an object: {path}")
    return payload


def _basic_auth_value(client_id: str, client_secret: str) -> str:
    credentials = f"{client_id}:{client_secret}".encode()
    return base64.b64encode(credentials).decode("ascii")


def _bounded_page_size(page_size: int) -> int:
    if page_size < 1:
        raise ValueError("page_size must be at least 1.")
    return min(page_size, 50)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
