from __future__ import annotations

from mangum import Mangum

from music_recommender.api.app import app

handler = Mangum(app, lifespan="off")
