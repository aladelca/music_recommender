# Music Recommender

Local data extraction pipeline for an educational music recommender project.

## Setup

```bash
uv sync
```

Copy `.env.example` values into `.env` and keep real credentials local. The repo already ignores `.env`.

Required Spotify variables:

```bash
SPOTIFY_APP_CLIENT_ID=...
SPOTIFY_APP_CLIENT_SECRET=...
```

## S3 Bootstrap

```bash
bash scripts/bootstrap_s3_medallion.sh
```

The script creates or verifies a bucket named `music-recommender-<account>-<region>` unless `MUSIC_RECOMMENDER_BUCKET` is already set.

## Local Extraction

Local mode calls APIs but writes files locally under `data/local/<run_id>/`.
Data tables default to Parquet. Run metadata stays JSON.

```bash
uv run music-recommender-extract \
  --seeds docs/base.md \
  --output local \
  --file-format parquet \
  --audio-feature-source reccobeats \
  --max-tracks-per-artist 5
```

Use `--log-level DEBUG` for more detailed per-album and lyric lookup logs.

## S3 Extraction

```bash
uv run music-recommender-extract \
  --seeds docs/base.md \
  --output s3 \
  --file-format parquet \
  --audio-feature-source reccobeats \
  --max-tracks-per-artist 150 \
  --bucket "$MUSIC_RECOMMENDER_BUCKET"
```

ReccoBeats is the default audio-feature source because Spotify audio features may be unavailable
for newer apps. Spotify can still be selected explicitly when access is available:

```bash
ENABLE_SPOTIFY_AUDIO_FEATURES=true uv run music-recommender-extract \
  --seeds docs/base.md \
  --output s3 \
  --max-tracks-per-artist 150 \
  --bucket "$MUSIC_RECOMMENDER_BUCKET" \
  --audio-feature-source spotify \
  --enable-audio-features
```

## Lyrics NLP

Lyrics NLP is optional because it downloads/loads local models.

```bash
uv sync --extra nlp
uv run music-recommender-extract \
  --seeds docs/base.md \
  --output local \
  --file-format parquet \
  --audio-feature-source reccobeats \
  --enable-lyrics-nlp \
  --max-tracks-per-artist 2
```

Language detection uses fastText `lid.176.ftz` and stores the model under
`~/.cache/music-recommender/models/` by default. Sentiment uses
`cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual`.

## Network Data

Spotify does not expose public "who likes/listened to which song" data. For educational
collaborative-filtering data, use public ListenBrainz dumps.

```bash
uv run music-recommender-network \
  --source listenbrainz \
  --dump-path "$LISTENBRAINZ_DUMP_PATH" \
  --output local \
  --file-format parquet \
  --catalog-tracks-path data/local/<catalog-run-id>/silver/tracks \
  --catalog-run-id <catalog-run-id> \
  --limit 10000
```

## Beta Demo Readiness

Phase 0 checks that local recommender data is readable and that Spotify user OAuth can refresh a
token for profile reads and playlist creation. Keep real tokens in `.env`; do not commit them.

Required demo variables:

```bash
OPENAI_API_KEY=...
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080/spotify/callback
SPOTIFY_USER_REFRESH_TOKEN=...
SPOTIFY_DEMO_USER_ID=12175364859
SPOTIFY_USER_SCOPES="user-top-read user-library-read playlist-modify-private playlist-modify-public"
RECOMMENDER_DATA_ROOT=data/local
RECOMMENDER_DATA_MODE=local
```

Generate the Spotify authorization URL:

```bash
uv run music-recommender-demo-readiness auth-url
```

After approving the app in Spotify and copying the returned `code`, exchange it locally. Use
`--show-refresh-token` only when you are ready to copy the token into `.env`.

```bash
uv run music-recommender-demo-readiness exchange-code \
  --code "<spotify-callback-code>" \
  --show-refresh-token
```

Validate the local extracted catalog inputs:

```bash
uv run music-recommender-demo-readiness check-data \
  --data-root data/local \
  --run-id smoke-reccobeats-parquet
```

Validate that the configured refresh token can produce a new user access token without printing the
access token value:

```bash
uv run music-recommender-demo-readiness refresh-spotify-token
```

## Validation

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest
```
