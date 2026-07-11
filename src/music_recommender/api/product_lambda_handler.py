from __future__ import annotations

from mangum import Mangum

from music_recommender.api.product_app import create_product_app

handler = Mangum(create_product_app(), lifespan="off")
