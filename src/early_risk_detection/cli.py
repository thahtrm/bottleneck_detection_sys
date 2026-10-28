"""``erd`` command line.

    erd score criticality --bundle bundles/criticality --db data/jira.duckdb --emb-dir data --out top.csv
    erd score delay       --bundle bundles/delay       --db data/jira.duckdb --emb-dir data --out risk.csv
    erd bundle info bundles/criticality
    erd etl   ...    (Mongo -> DuckDB ETL, same flags as ``python -m early_risk_detection.data.etl``)
    erd embed ...    (Ollama embeddings of every issue, ``early_risk_detection.embeddings``)
    erd eval criticality|delay ...   (evaluation harnesses)
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from ._logging import setup_logging

PASSTHROUGH = {
    "etl": ("early_risk_detection.data.etl.__main__", "Mongo -> DuckDB ETL"),
    "embed": ("early_risk_detection.embeddings", "Ollama text embeddings for a DuckDB"),
    "eval-criticality": ("early_risk_detection.evaluation.criticality", "criticality evaluation harness"),
    "eval-delay": ("early_risk_detection.evaluation.delay", "delay evaluation harness"),
}


def _embeddings(args):
    from .embeddings import EmbeddingIndex, OllamaEmbedder

    fallback = OllamaEmbedder(endpoint=args.ollama) if args.ollama else None
    if args.emb_dir:
        return EmbeddingIndex(args.emb_dir, fallback=fallback)
    if fallback is None:
        sys.exit("need --emb-dir (precomputed embeddings) and/or --ollama (embedding server)")
    return fallback


def _score(args) -> None:
    if args.model == "criticality":
        from .criticality import CriticalityScorer as Scorer
    else:
        from .delay import DelayRiskScorer as Scorer
    keys = None
    if args.keys_file:
        with open(args.keys_file) as f:
            keys = [k.strip() for k in f if k.strip()]
    scorer = Scorer.load(args.bundle, device=args.device)
    out = scorer.score(args.db, embeddings=_embeddings(args), issue_keys=keys,
                       as_of=pd.Timestamp(args.as_of, tz="UTC") if args.as_of else None,
                       open_only=not args.all_issues, stream_dir=args.stream_dir)
    if args.out:
        out.to_csv(args.out, index=False)
        print(f"wrote {len(out):,} rows to {args.out}")
    else:
        print(out.head(args.head).to_string(index=False))


def _bundle_info(args) -> None:
    from .bundle import ModelBundle

    b = ModelBundle.load(args.path, verify=not args.no_verify)
    m = dict(b.manifest)
    m["files"] = sorted(m["files"])
    cfg = m.get("config", {})
    for k in ("static_features", "propensity_backoff", "features"):
        if isinstance(cfg.get(k), (list, dict)):
            cfg[k] = f"<{len(cfg[k])} entries>"
    print(json.dumps(m, indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in PASSTHROUGH:
        import importlib

        setup_logging()
        importlib.import_module(PASSTHROUGH[argv[0]][0]).main(argv[1:])
        return
    if argv[:1] == ["eval"] and len(argv) > 1 and f"eval-{argv[1]}" in PASSTHROUGH:
        import importlib

        importlib.import_module(PASSTHROUGH[f"eval-{argv[1]}"][0]).main(argv[2:])
        return

    ap = argparse.ArgumentParser(prog="erd", description="Early risk detection for Jira issues.",
                                 epilog="pass-through commands: " + ", ".join(
                                     f"{k} ({v[1]})" for k, v in PASSTHROUGH.items()).replace("eval-", "eval "))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score", help="score issues of a Jira DuckDB with a model bundle")
    sc.add_argument("model", choices=["criticality", "delay"])
    sc.add_argument("--bundle", required=True)
    sc.add_argument("--db", required=True, help="Jira DuckDB (schema of early_risk_detection.data.etl)")
    sc.add_argument("--emb-dir", help="directory with emb_uid_all.parquet + emb_unique_all_fp16.npy")
    sc.add_argument("--ollama", nargs="?", const="http://localhost:11434/api/embed",
                    help="embed issues missing from --emb-dir with this Ollama endpoint")
    sc.add_argument("--as-of", help="score issues open at this date (default: now)")
    sc.add_argument("--all-issues", action="store_true", help="score every issue created before --as-of")
    sc.add_argument("--keys-file", help="file with one instance|issue_key per line to score")
    sc.add_argument("--stream-dir", help="cache directory for the event stream (criticality)")
    sc.add_argument("--device", default=None)
    sc.add_argument("--out", help="CSV output (default: print the top rows)")
    sc.add_argument("--head", type=int, default=20)
    sc.set_defaults(func=_score)
    bi = sub.add_parser("bundle", help="inspect a model bundle")
    bi.add_argument("action", choices=["info"])
    bi.add_argument("path")
    bi.add_argument("--no-verify", action="store_true")
    bi.set_defaults(func=_bundle_info)
    args = ap.parse_args(argv)
    setup_logging()
    args.func(args)


if __name__ == "__main__":
    main()
