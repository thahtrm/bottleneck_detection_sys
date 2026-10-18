"""Tạo các đặc trưng Tầng 1 (Tier 1 Semantic & Ambiguity Features) từ Ollama Embeddings.
Hỗ trợ cả chế độ memmap toàn cục (2.68M issues - `--instance ALL`) và chế độ file `.npy` đơn lẻ.
Đảm bảo ZERO Temporal Data Leakage:
- TruncatedSVD (16 components) và Logistic Semantic Classifier chỉ được fit trên tập Train.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from prepare_censored_dataset import attach_embeddings_and_split, build_base_chronological_features


def main():
    parser = argparse.ArgumentParser(description="Enrich Tier 1 Semantic Features from Ollama Embeddings")
    parser.add_argument("--duckdb-path", type=str, default="data/jira.duckdb")
    parser.add_argument("--instance", type=str, default="ALL")
    parser.add_argument("--out-dir", type=str, default="data")
    args = parser.parse_args()

    base_cache = build_base_chronological_features(
        duckdb_path=args.duckdb_path,
        instance=args.instance,
        out_dir=args.out_dir,
    )
    attach_embeddings_and_split(
        base_cache_file=base_cache,
        instance=args.instance,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
