from __future__ import annotations

import ast
from pathlib import Path

DISCOVERY_MODULES = (
    Path("src/music_recommender/api/cleanup_handler.py"),
    Path("src/music_recommender/api/discovery_worker_handler.py"),
    Path("src/music_recommender/product/account_service.py"),
    Path("src/music_recommender/product/discovery_queue.py"),
    Path("src/music_recommender/product/discovery_service.py"),
    Path("src/music_recommender/product/feedback_service.py"),
    Path("src/music_recommender/product/playlist_export_service.py"),
    Path("src/music_recommender/product/recommendation_service.py"),
    Path("src/music_recommender/product/spotify_mapping.py"),
    Path("src/music_recommender/sources/listenbrainz_api.py"),
)
FORBIDDEN_IMPORTS = {
    "csv",
    "pandas",
    "polars",
    "pyarrow",
    "music_recommender.storage.s3",
}
FORBIDDEN_CALLS = {"open", "Path.read_bytes", "Path.read_text"}


def test_automated_discovery_has_no_local_or_s3_data_path() -> None:
    for module_path in DISCOVERY_MODULES:
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        imported = _imports(tree)
        calls = _calls(tree)

        assert not imported.intersection(FORBIDDEN_IMPORTS), module_path
        assert not calls.intersection(FORBIDDEN_CALLS), module_path
        assert ".csv" not in module_path.read_text(encoding="utf-8").casefold()
        assert ".parquet" not in module_path.read_text(encoding="utf-8").casefold()


def _imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def _calls(tree: ast.AST) -> set[str]:
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "Path"
        ):
            calls.add(f"Path.{node.func.attr}")
    return calls
