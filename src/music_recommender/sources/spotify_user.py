from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from music_recommender.models import JsonDict
from music_recommender.sources.http import ApiError, ApiHttpClient

AUTH_BASE_URL = "https://accounts.spotify.com"
API_BASE_URL = "https://api.spotify.com/v1"

TopItemType = Literal["artists", "tracks"]
TopTimeRange = Literal["short_term", "medium_term", "long_term"]
_PKCE_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


class SpotifyClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SpotifyReauthorizationRequired(SpotifyClientError):
    pass


class SpotifyPermissionDenied(SpotifyClientError):
    pass


class SpotifyRateLimited(SpotifyClientError):
    pass


class SpotifyServiceUnavailable(SpotifyClientError):
    pass


class SpotifyResponseError(SpotifyClientError):
    pass


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
    code_challenge: str | None = None,
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
    if code_challenge is not None:
        _validate_pkce_challenge(code_challenge)
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{AUTH_BASE_URL}/authorize?{urllib.parse.urlencode(params)}"


def generate_pkce_verifier(*, length: int = 64) -> str:
    if not 43 <= length <= 128:
        raise ValueError("PKCE verifier length must be between 43 and 128 characters.")
    return "".join(secrets.choice(_PKCE_CHARACTERS) for _ in range(length))


def pkce_code_challenge(code_verifier: str) -> str:
    _validate_pkce_verifier(code_verifier)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


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
        refresh_token_updated: Callable[[str], None] | None = None,
        auth_http: ApiHttpClient | None = None,
        api_http: ApiHttpClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.refresh_token_updated = refresh_token_updated
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
        code_verifier: str | None = None,
        required_scopes: tuple[str, ...] = (),
    ) -> SpotifyAccessToken:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier is not None:
            _validate_pkce_verifier(code_verifier)
            data["code_verifier"] = code_verifier
        payload = self._request_token(data=data)
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

    def get_current_account_id(self) -> str:
        account_id = _optional_str(self.get_current_user_profile().get("account_id"))
        if not account_id:
            raise SpotifyResponseError("Spotify response did not include a valid account_id.")
        return account_id

    def search_tracks(
        self,
        query: str,
        *,
        limit: int = 5,
        market: str | None = None,
    ) -> tuple[JsonDict, ...]:
        normalized_query = " ".join(query.split())
        if not 1 <= len(normalized_query) <= 250:
            raise ValueError("Spotify track search query must be between 1 and 250 characters.")
        if not 1 <= limit <= 10:
            raise ValueError("Spotify track search limit must be between 1 and 10.")
        params: dict[str, str | int] = {
            "q": normalized_query,
            "type": "track",
            "limit": limit,
        }
        if market:
            params["market"] = market
        payload = self._get("/search", params=params)
        tracks = payload.get("tracks")
        if not isinstance(tracks, dict):
            return ()
        items = tracks.get("items")
        if not isinstance(items, list):
            return ()
        return tuple(dict(item) for item in items[:limit] if isinstance(item, dict))

    def get_tracks(
        self,
        track_ids: tuple[str, ...],
        *,
        market: str | None = None,
    ) -> tuple[JsonDict, ...]:
        normalized_ids = tuple(dict.fromkeys(_spotify_id(track_id) for track_id in track_ids))
        if not 1 <= len(normalized_ids) <= 50:
            raise ValueError("Spotify track lookup accepts between 1 and 50 unique IDs.")
        params: dict[str, str] = {"ids": ",".join(normalized_ids)}
        if market:
            params["market"] = market
        payload = self._get("/tracks", params=params)
        tracks = payload.get("tracks")
        if not isinstance(tracks, list):
            return ()
        return tuple(dict(track) for track in tracks if isinstance(track, dict))

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
        *,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> JsonDict:
        return self._post(
            "/me/playlists",
            json={"name": name, "description": description, "public": public},
            expected_statuses=(200, 201),
            retry=False,
        )

    def add_playlist_items(self, playlist_id: str, track_ids_or_uris: list[str]) -> JsonDict:
        if not track_ids_or_uris:
            raise ValueError("At least one Spotify track ID or URI is required.")
        if len(track_ids_or_uris) > 100:
            raise ValueError("Spotify accepts at most 100 playlist items per request.")
        uris = [spotify_track_uri(track_id_or_uri) for track_id_or_uri in track_ids_or_uris]
        return self._post(
            f"/playlists/{playlist_id}/items",
            json={"uris": uris},
            expected_statuses=(200, 201),
            retry=False,
        )

    def replace_playlist_items(
        self,
        playlist_id: str,
        track_ids_or_uris: list[str],
    ) -> JsonDict:
        if not track_ids_or_uris:
            raise ValueError("At least one Spotify track ID or URI is required.")
        if len(track_ids_or_uris) > 100:
            raise ValueError("Spotify accepts at most 100 playlist items per request.")
        uris = [spotify_track_uri(track_id_or_uri) for track_id_or_uri in track_ids_or_uris]
        return self._put(
            f"/playlists/{_spotify_id(playlist_id)}/items",
            json={"uris": uris},
            expected_statuses=(200, 201),
        )

    def _request_token(self, *, data: dict[str, str]) -> JsonDict:
        basic_authorization = _basic_auth_value(self.client_id, self.client_secret)
        try:
            response = self.auth_http.post(
                "/api/token",
                headers={
                    "Authorization": f"Basic {basic_authorization}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=data,
            )
        except ApiError as error:
            raise _classify_spotify_error(error, token_request=True) from None
        return _json_object(response.json(), "/api/token")

    def _store_token(self, token: SpotifyAccessToken) -> None:
        if token.refresh_token and token.refresh_token != self.refresh_token:
            if self.refresh_token_updated is not None:
                self.refresh_token_updated(token.refresh_token)
            self.refresh_token = token.refresh_token
        self._access_token = token.access_token
        self._expires_at = time.time() + token.expires_in

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
        try:
            response = self.api_http.get(
                path,
                headers={"Authorization": f"Bearer {self.get_access_token()}"},
                **kwargs,
            )
        except ApiError as error:
            if error.status_code == 401:
                self._clear_access_token()
            raise _classify_spotify_error(error) from None
        return _json_object(response.json(), path)

    def _post(self, path: str, **kwargs: Any) -> JsonDict:
        try:
            response = self.api_http.post(
                path,
                headers={"Authorization": f"Bearer {self.get_access_token()}"},
                **kwargs,
            )
        except ApiError as error:
            if error.status_code == 401:
                self._clear_access_token()
            raise _classify_spotify_error(error) from None
        return _json_object(response.json(), path)

    def _put(self, path: str, **kwargs: Any) -> JsonDict:
        try:
            response = self.api_http.put(
                path,
                headers={"Authorization": f"Bearer {self.get_access_token()}"},
                **kwargs,
            )
        except ApiError as error:
            if error.status_code == 401:
                self._clear_access_token()
            raise _classify_spotify_error(error) from None
        return _json_object(response.json(), path)

    def _clear_access_token(self) -> None:
        self._access_token = None
        self._expires_at = 0.0

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


def _spotify_id(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 255
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError("Spotify ID is invalid.")
    return normalized


def _validate_pkce_verifier(code_verifier: str) -> None:
    if not 43 <= len(code_verifier) <= 128:
        raise ValueError("PKCE verifier length must be between 43 and 128 characters.")
    if any(character not in _PKCE_CHARACTERS for character in code_verifier):
        raise ValueError("PKCE verifier contains invalid characters.")


def _validate_pkce_challenge(code_challenge: str) -> None:
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    if len(code_challenge) != 43 or any(character not in allowed for character in code_challenge):
        raise ValueError("PKCE S256 challenge must be a 43-character base64url value.")


def _classify_spotify_error(
    error: ApiError,
    *,
    token_request: bool = False,
) -> SpotifyClientError:
    status_code = error.status_code
    if status_code == 401 or (token_request and status_code == 400):
        return SpotifyReauthorizationRequired(
            "Spotify authorization is no longer valid; reconnect the account.",
            status_code=status_code,
        )
    if status_code == 403:
        return SpotifyPermissionDenied(
            "Spotify denied this operation for the current account.",
            status_code=status_code,
        )
    if status_code == 429:
        return SpotifyRateLimited(
            "Spotify rate limit remained active after bounded retries.",
            status_code=status_code,
        )
    if 500 <= status_code <= 599:
        return SpotifyServiceUnavailable(
            "Spotify is temporarily unavailable after bounded retries.",
            status_code=status_code,
        )
    return SpotifyClientError("Spotify request failed.", status_code=status_code)
