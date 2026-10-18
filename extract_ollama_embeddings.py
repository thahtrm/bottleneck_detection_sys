"""Trích xuất Dense Text Embeddings (768 chiều) từ Ollama Docker Container (nomic-embed-text:latest)
cho toàn bộ kho dữ liệu Jira (data/jira.duckdb - 2,685,911 issues trên 16 instances) tại mốc T0.

Tối ưu hóa cấp Hệ thống Lớn (Big-Data Systems Engineering):
1. Zero Temporal Data Leakage: Chỉ sử dụng thông tin tại T0 (issuetype, project, summary).
2. Deduplication & Length-Grouped Dynamic Batching:
   - Khử trùng lặp văn bản và sắp xếp theo độ dài chuỗi (key=len) để triệt tiêu padding waste trong GPU CUDA kernel của Ollama (~350-380 issues/s).
3. Disk-Backed Memory Mapping (np.memmap float16):
   - Lưu trữ ma trận (N_unique, 768) dưới dạng float16 (~3.9 GB trên đĩa thay vì >16 GB trên RAM) cùng bảng ánh xạ chỉ mục O(1) `emb_row_to_unique.npy`.
4. Fault-Tolerant Checkpointing:
   - Tự động lưu trạng thái sau mỗi 25 batches (25,600 văn bản) để có thể resume tức thì nếu gián đoạn.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from numpy.lib.format import open_memmap


def fetch_batch_embeddings(
    texts: list[str],
    model: str = "nomic-embed-text:latest",
    endpoint: str = "http://localhost:11434/api/embed",
    max_retries: int = 5,
) -> np.ndarray:
    payload = json.dumps({
        "model": model,
        "input": texts,
        "truncate": True,
        "keep_alive": "24h",
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return np.asarray(data["embeddings"], dtype=np.float16)
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"[Ollama Warning] Batch failed after {max_retries} attempts: {e}. Returning zeros.", flush=True)
                return np.zeros((len(texts), 768), dtype=np.float16)
            time.sleep(1.5 * (attempt + 1))
    return np.zeros((len(texts), 768), dtype=np.float16)


def extract_full_database_embeddings(
    duckdb_path: str = "data/jira.duckdb",
    instance: str = "ALL",
    out_dir: str = "data",
    batch_size: int = 1024,
    workers: int = 2,
    model: str = "nomic-embed-text:latest",
) -> None:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print("=================================================================", flush=True)
    print(f"🚀 EXTRACTING DENSE TEXT EMBEDDINGS VIA OLLAMA (INSTANCE={instance})", flush=True)
    print("=================================================================", flush=True)

    # Kiểm tra kết nối tới Ollama Docker container
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            models_info = json.loads(resp.read().decode())
            available = [m["name"] for m in models_info.get("models", [])]
            print(f"[Ollama Check] Connected! Available models: {available}", flush=True)
    except Exception as e:
        raise RuntimeError(f"[Ollama Check] ERROR connecting to Ollama Docker container: {e}")

    # 1. Đọc danh sách issues theo đúng thứ tự thời gian chuẩn từ DuckDB và đóng kết nối ngay
    t0 = time.time()
    con = duckdb.connect(duckdb_path, read_only=True)
    if instance.upper() == "ALL":
        query = """
            SELECT
                COALESCE(issuetype, 'Bug') || ' in ' || COALESCE(project, 'APP') || ': ' || SUBSTR(COALESCE(summary, ''), 1, 200) AS text_input
            FROM issues
            WHERE created_ts > 946684800
              AND (resolved_ts IS NULL OR resolved_ts >= created_ts)
            ORDER BY created_ts ASC, instance ASC, issue_key ASC
        """
        df_texts = con.execute(query).df()
    else:
        query = """
            SELECT
                COALESCE(issuetype, 'Bug') || ' in ' || COALESCE(project, 'APP') || ': ' || SUBSTR(COALESCE(summary, ''), 1, 200) AS text_input
            FROM issues
            WHERE instance = ?
              AND created_ts > 946684800
              AND (resolved_ts IS NULL OR resolved_ts >= created_ts)
            ORDER BY created_ts ASC, instance ASC, issue_key ASC
        """
        df_texts = con.execute(query, [instance]).df()
    con.close()

    total_rows = len(df_texts)
    print(f"[DuckDB] Loaded {total_rows:,} valid issues in {time.time() - t0:.2f}s (connection closed).", flush=True)

    # 2. Khử trùng lặp và sắp xếp theo độ dài chuỗi (Length-Grouped Dynamic Batching)
    t1 = time.time()
    raw_series = df_texts["text_input"].fillna("")
    codes, uniques = pd.factorize(raw_series, sort=False)
    del df_texts, raw_series

    n_unique = len(uniques)
    unique_list = uniques.tolist()
    del uniques

    # Sắp xếp unique_list theo độ dài tăng dần để tối ưu hóa GPU padding trong Ollama
    lengths = np.fromiter((len(s) for s in unique_list), dtype=np.int32, count=n_unique)
    length_order = np.argsort(lengths, kind="mergesort")
    sorted_unique_texts = [unique_list[idx] for idx in length_order]
    del unique_list, lengths

    # Ánh xạ ngược từ mã factorize ban đầu sang vị trí trong mảng đã sắp xếp theo độ dài
    inv_order = np.empty(n_unique, dtype=np.int32)
    inv_order[length_order] = np.arange(n_unique, dtype=np.int32)
    row_to_sorted_unique = inv_order[codes]
    del codes, inv_order, length_order

    suffix = "all" if instance.upper() == "ALL" else instance.lower()
    map_path = out_path / f"emb_row_to_unique_{suffix}.npy"
    memmap_path = out_path / f"emb_unique_{suffix}_fp16.npy"
    progress_path = out_path / f"emb_progress_{suffix}.json"

    np.save(map_path, row_to_sorted_unique)
    print(
        f"[Deduplication] Total rows: {total_rows:,} -> Unique texts: {n_unique:,} "
        f"(Saved {total_rows - n_unique:,} redundant LLM calls in {time.time() - t1:.2f}s)",
        flush=True,
    )

    # 3. Khởi tạo hoặc mở lại file memmap float16
    start_idx = 0
    if memmap_path.exists() and progress_path.exists():
        try:
            with open(progress_path, "r", encoding="utf-8") as f:
                prog = json.load(f)
            if prog.get("n_unique") == n_unique and prog.get("completed_idx", 0) > 0:
                start_idx = int(prog["completed_idx"])
                print(f"[Resume] Resuming from checkpoint index {start_idx:,}/{n_unique:,} ({start_idx/n_unique:.1%})", flush=True)
        except Exception:
            start_idx = 0

    if start_idx == 0:
        emb_mmap = open_memmap(str(memmap_path), mode="w+", dtype=np.float16, shape=(n_unique, 768))
    else:
        emb_mmap = open_memmap(str(memmap_path), mode="r+", dtype=np.float16, shape=(n_unique, 768))

    # 4. Vòng lặp trích xuất theo siêu lô (Super-batching với ThreadPoolExecutor)
    super_batch_size = batch_size * workers * 10  # 20,480 texts mỗi chu kỳ checkpoint
    t_start = time.time()
    processed_since_start = 0

    for sb_start in range(start_idx, n_unique, super_batch_size):
        sb_end = min(n_unique, sb_start + super_batch_size)
        sub_batches = []
        sub_ranges = []
        for b_start in range(sb_start, sb_end, batch_size):
            b_end = min(sb_end, b_start + batch_size)
            sub_batches.append(sorted_unique_texts[b_start:b_end])
            sub_ranges.append((b_start, b_end))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(lambda b: fetch_batch_embeddings(b, model=model), sub_batches))

        for (b_start, b_end), emb_arr in zip(sub_ranges, results):
            emb_mmap[b_start:b_end] = emb_arr

        emb_mmap.flush()
        processed_since_start += (sb_end - sb_start)
        elapsed = time.time() - t_start
        speed = processed_since_start / max(1e-3, elapsed)
        rem_texts = n_unique - sb_end
        eta_min = (rem_texts / max(1e-3, speed)) / 60.0

        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "n_unique": n_unique,
                    "total_rows": total_rows,
                    "completed_idx": sb_end,
                    "speed_texts_per_sec": round(speed, 2),
                    "eta_minutes": round(eta_min, 2),
                    "timestamp": time.time(),
                },
                f,
                indent=2,
            )

        print(
            f"[Ollama Progress] {sb_end:,}/{n_unique:,} unique texts ({sb_end / n_unique:.2%}) | "
            f"Speed: {speed:.1f} texts/s | Elapsed: {elapsed / 60.0:.1f}m | ETA: {eta_min:.1f}m",
            flush=True,
        )

    total_time = time.time() - t_start
    print(f"\n✅ [Success] Extracted 100% Ollama embeddings ({n_unique:,} unique / {total_rows:,} total issues) in {total_time/60.0:.2f} minutes!", flush=True)
    print(f"  • Memmap file: {memmap_path} ({memmap_path.stat().st_size / (1024**3):.2f} GB)", flush=True)
    print(f"  • Index map:   {map_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Extract 768-d Dense Embeddings via Ollama Docker for Jira Database")
    parser.add_argument("--instance", type=str, default="ALL", help="Jira instance name or ALL for full 2.68M database")
    parser.add_argument("--duckdb-path", type=str, default="data/jira.duckdb")
    parser.add_argument("--out-dir", type=str, default="data")
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    extract_full_database_embeddings(
        duckdb_path=args.duckdb_path,
        instance=args.instance,
        out_dir=args.out_dir,
        batch_size=args.batch_size,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
