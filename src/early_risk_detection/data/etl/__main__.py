"""CLI Driver cho pipeline ETL MongoDB -> DuckDB.

Cách chạy:
    # 1. Liệt kê các instance trong MongoDB
    python -m early_risk_detection.data.etl --list

    # 2. Chạy ETL cho 1 instance (JFrog)
    python -m early_risk_detection.data.etl --instance JFrog --duckdb data/jira.duckdb --overwrite

    # 3. Chạy ETL pilot với giới hạn số lượng issue
    python -m early_risk_detection.data.etl --instance Mojang --limit 20000 --overwrite

    # 4. Xem thống kê dữ liệu hiện có trong DuckDB
    python -m early_risk_detection.data.etl --stats --instance JFrog --duckdb data/jira.duckdb
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import ETLConfig
from .extractor import MongoStreamExtractor
from .loader import DuckDBLoader
from .pipeline import ETLPipeline


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="ETL pipeline: MongoDB -> DuckDB cho The Public Jira Dataset")
    ap.add_argument("--host", default="127.0.0.1:27017", help="Địa chỉ MongoDB (mặc định 127.0.0.1:27017)")
    ap.add_argument("--db", default="JiraReposAnon", help="Tên DB MongoDB (mặc định JiraReposAnon)")
    ap.add_argument("--duckdb", default="data/jira.duckdb", help="Đường dẫn file DuckDB (mặc định data/jira.duckdb)")
    ap.add_argument("--instance", default=None, help="Tên instance cần ETL (JFrog, Spring, Mojang, ...)")
    ap.add_argument("--all", action="store_true", help="Chạy ETL cho tất cả các instance tìm thấy")
    ap.add_argument("--list", action="store_true", help="Liệt kê các instance và số issue trong MongoDB")
    ap.add_argument("--batch-size", type=int, default=5000, help="Số lượng issue trong 1 batch streaming (mặc định 5000)")
    ap.add_argument("--limit", type=int, default=None, help="Giới hạn số lượng issue trích xuất")
    ap.add_argument("--overwrite", action="store_true", help="Xóa dữ liệu cũ của instance trong DuckDB trước khi nạp")
    ap.add_argument("--stats", action="store_true", help="Xem số lượng bản ghi của instance trong DuckDB")

    args = ap.parse_args(argv)

    if args.list:
        extractor = MongoStreamExtractor(host=args.host, db_name=args.db)
        try:
            extractor.ping()
        except Exception as ex:
            sys.exit(f"[Lỗi kết nối MongoDB] Không thể ping tới {args.host}: {ex}\nHãy đảm bảo mongod đang chạy.")
        instances = extractor.list_instances()
        print(f"\nDanh sách {len(instances)} instance trong MongoDB ({args.db}):")
        print("-" * 40)
        for row in instances:
            print(f"{row['instance']:<20} {row['n_issues']:>12,} issues")
        print("-" * 40)
        return

    if args.stats:
        loader = DuckDBLoader(duckdb_path=args.duckdb)
        inst = args.instance
        if not inst:
            sys.exit("Cần cung cấp --instance để xem stats (hoặc truy vấn trực tiếp file DuckDB)")
        stats = loader.get_instance_stats(inst)
        print(json.dumps(stats, indent=2))
        return

    if not args.instance and not args.all:
        ap.error("Chọn --list | --instance <tên> | --all | --stats")

    cfg = ETLConfig(
        mongo_host=args.host,
        mongo_db=args.db,
        duckdb_path=args.duckdb,
        batch_size=args.batch_size,
        overwrite=args.overwrite,
    )

    pipeline = ETLPipeline(cfg)
    try:
        pipeline.extractor.ping()
    except Exception as ex:
        sys.exit(f"[Lỗi kết nối MongoDB] Không thể kết nối tới {args.host}: {ex}\nHãy khởi động mongod trước khi chạy.")

    try:
        if args.all:
            res = pipeline.run_all(limit=args.limit, overwrite=args.overwrite)
        else:
            res = pipeline.run_instance(args.instance, limit=args.limit, overwrite=args.overwrite)
        print("\nKết quả ETL:")
        print(json.dumps(res, indent=2))
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
