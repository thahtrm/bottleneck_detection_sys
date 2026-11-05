"""Pipeline Orchestrator: Điều phối trích xuất, chuyển đổi và nạp dữ liệu."""
from __future__ import annotations

import sys
import time
from typing import Any

from .config import ETLConfig
from .extractor import MongoStreamExtractor
from .loader import DuckDBLoader
from .transformer import JiraTransformer


class ETLPipeline:
    def __init__(self, config: ETLConfig | None = None) -> None:
        self.config = config or ETLConfig()
        self.extractor = MongoStreamExtractor(
            host=self.config.mongo_host,
            db_name=self.config.mongo_db,
        )
        self.transformer = JiraTransformer(
            preview_len=self.config.preview_len,
        )
        self.loader = DuckDBLoader(
            duckdb_path=self.config.duckdb_path,
        )

    def run_instance(
        self,
        instance: str,
        limit: int | None = None,
        overwrite: bool | None = None,
    ) -> dict[str, Any]:
        """Thực thi ETL cho 1 instance."""
        is_overwrite = self.config.overwrite if overwrite is None else overwrite
        t0 = time.time()

        print(f"\n[ETL] === Bắt đầu xử lý instance: {instance} ===", file=sys.stderr)
        self.loader.init_schema()

        try:
            total_docs = self.extractor.count_instance(instance)
        except Exception:
            total_docs = 0

        target_docs = min(total_docs, limit) if limit and total_docs > 0 else (limit or total_docs)
        print(f"[ETL] Tổng số issue nguồn: {total_docs:,} (mục tiêu nạp: {target_docs:,})", file=sys.stderr)

        existing_stats = self.loader.get_instance_stats(instance)
        existing_issues = existing_stats.get("n_issues", 0)

        if not is_overwrite and existing_issues >= target_docs and target_docs > 0:
            print(f"[ETL] Instance '{instance}' đã nạp đủ {existing_issues:,} issues trong DuckDB — bỏ qua (dùng --overwrite để nạp lại)", file=sys.stderr)
            existing_stats["status"] = "skipped_already_exists"
            return existing_stats

        if is_overwrite or existing_issues > 0:
            if existing_issues > 0:
                print(f"[ETL] Xóa dữ liệu cũ ({existing_issues:,} issues) của '{instance}' trong DuckDB...", file=sys.stderr)
            self.loader.clear_instance(instance)

        processed = 0
        batch_idx = 0
        batches = self.extractor.stream_batches(
            instance=instance,
            batch_size=self.config.batch_size,
            limit=limit,
        )

        for chunk in batches:
            batch_idx += 1
            batch_data = self.transformer.transform_batch(chunk, instance)
            self.loader.load_batch(batch_data)
            processed += len(chunk)

            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            pct = (processed / target_docs * 100) if target_docs > 0 else 0
            print(
                f"[ETL] Batch {batch_idx:>3}: đã nạp {processed:>8,} / {target_docs:,} issues "
                f"({pct:5.1f}%) | Tốc độ: {rate:7.1f} docs/s",
                file=sys.stderr,
            )

        elapsed = time.time() - t0
        stats = self.loader.get_instance_stats(instance)
        stats["elapsed_seconds"] = round(elapsed, 2)
        stats["docs_per_second"] = round(processed / elapsed, 1) if elapsed > 0 else 0
        stats["duckdb_path"] = self.config.duckdb_path

        print(
            f"[ETL] Hoàn thành '{instance}': {stats['n_issues']:,} issues, "
            f"{stats['n_changelogs']:,} changelogs, {stats['n_links']:,} links, "
            f"{stats['n_comments']:,} comments, {stats['n_tgn_events']:,} events "
            f"trong {elapsed:.2f}s ({stats['docs_per_second']:.1f} docs/s)\n",
            file=sys.stderr,
        )

        return stats

    def run_all(
        self,
        limit: int | None = None,
        overwrite: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Thực thi ETL cho toàn bộ các instance tìm thấy trong MongoDB."""
        self.extractor.ping()
        inst_meta = sorted(self.extractor.list_instances(), key=lambda r: r["n_issues"])
        instances = [r["instance"] for r in inst_meta]
        summary_str = ", ".join(f"{r['instance']} ({r['n_issues']:,})" for r in inst_meta)
        print(f"[ETL] Tìm thấy {len(instances)} instance trong MongoDB: {summary_str}", file=sys.stderr)

        results = []
        for name in instances:
            try:
                res = self.run_instance(name, limit=limit, overwrite=overwrite)
                results.append(res)
            except Exception as ex:
                results.append({"instance": name, "error": str(ex)})

        print("[ETL] Đang tạo các chỉ mục (indexes) trên DuckDB...", file=sys.stderr)
        try:
            self.loader.create_indexes()
            print("[ETL] Hoàn tất tạo chỉ mục trên DuckDB thành công!", file=sys.stderr)
        except Exception as ex:
            print(f"[ETL] Cảnh báo khi tạo chỉ mục: {ex}", file=sys.stderr)

        return results

    def close(self) -> None:
        self.extractor.close()
        self.loader.close()


def run_etl(
    instance: str | None = None,
    all_instances: bool = False,
    mongo_host: str = "127.0.0.1:27017",
    mongo_db: str = "JiraReposAnon",
    duckdb_path: str = "data/jira.duckdb",
    batch_size: int = 5000,
    limit: int | None = None,
    overwrite: bool = False,
) -> Any:
    """Entry point tiện lợi để gọi từ code Python."""
    cfg = ETLConfig(
        mongo_host=mongo_host,
        mongo_db=mongo_db,
        duckdb_path=duckdb_path,
        batch_size=batch_size,
        overwrite=overwrite,
    )
    pipeline = ETLPipeline(cfg)
    try:
        if all_instances:
            return pipeline.run_all(limit=limit, overwrite=overwrite)
        elif instance:
            return pipeline.run_instance(instance, limit=limit, overwrite=overwrite)
        else:
            raise ValueError("Cần chỉ định 'instance' hoặc 'all_instances=True'")
    finally:
        pipeline.close()
