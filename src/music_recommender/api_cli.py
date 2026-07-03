from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from dotenv import load_dotenv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the music recommender API locally.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runner: Callable[..., None] | None = None,
) -> int:
    load_dotenv(".env")
    args = build_parser().parse_args(argv)
    if runner is None:
        import uvicorn

        runner = uvicorn.run
    runner(
        "music_recommender.api.app:app",
        host=str(args.host),
        port=int(args.port),
        reload=bool(args.reload),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
