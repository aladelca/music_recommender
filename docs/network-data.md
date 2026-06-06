# Network Data

Spotify is not a public source for "who likes which song or album" data. The Web API can read
only the authenticated user's saved tracks, saved albums, top items, playlists, followed artists,
or recent plays when that user grants OAuth scopes. That works for a future app with consenting
users, but it does not create a public collaborative-filtering dataset.

For this educational recommender, use ListenBrainz public dumps first. They provide user-submitted
listens that can be normalized into implicit user-item interactions:

- `bronze/network/listenbrainz`: normalized raw listen rows.
- `silver/network/listens`: cleaned listen rows with hashed users.
- `gold/user_track_interactions`: aggregate `user_id_hash`, `item_id`, and `listen_count`.

Example:

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

User identifiers are hashed before storage. If you later ingest first-party user data, keep the
same privacy rule and store only consented fields.

When `--catalog-tracks-path` is provided, the network pipeline links ListenBrainz listens to the
catalog run by:

1. `spotify_track_id`
2. `isrc`
3. normalized `artist_name + track_name`

Linked outputs are written to:

- `silver/network/listens_linked`
- `gold/catalog_user_track_interactions`
