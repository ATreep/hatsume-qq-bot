#!/usr/bin/env python3
"""Copy legacy SQLite memory vectors into the local Milvus Lite database."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

from langchain_openai import OpenAIEmbeddings


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read memory vectors from SQLite without modifying it and upsert them "
            "into Milvus Lite."
        )
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=ROOT / "data/hatsume-plugin/memory-db/memory.db",
    )
    parser.add_argument(
        "--milvus",
        type=Path,
        default=ROOT / "data/hatsume-plugin/memory-db/memory_vectors.db",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = _load_module("hatsume_memory_migration_config", PLUGIN_DIR / "config.py")
    vectors = _load_module(
        "hatsume_memory_migration_vector_store",
        PLUGIN_DIR / "memory/vector_store.py",
    )
    embedding_model = OpenAIEmbeddings(
        base_url=config.get_base_url("sf"),
        model=config.EMBEDDING_MODEL,
        api_key=config.get_api_key("sf"),
        chunk_size=32,
    )
    vector_store = vectors.MilvusVectorStore(args.milvus, dimension=1024)
    try:
        report = vectors.migrate_sqlite_vectors(
            args.sqlite,
            vector_store,
            embedding_model.embed_documents,
            batch_size=args.batch_size,
        )
    finally:
        vector_store.close()

    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    return int(report.failed > 0 or report.verified != report.total)


if __name__ == "__main__":
    raise SystemExit(main())
