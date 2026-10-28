# early-risk-detection

Thư viện phát hiện sớm rủi ro trong Jira, chấm điểm **ngay tại thời điểm tạo issue (T0)**:

| Mô hình | Câu hỏi | Kiến trúc | Đầu ra chính |
|---|---|---|---|
| **Delay risk** (`DelayRiskScorer`) | Task này có trễ hạn so với SLA không? | XGBoost 5-fold + XGBoost AFT + CatBoost AFT + P(non-work), cổng pre-triage (non-work / trùng lặp ngữ nghĩa) | `p_delay`, `is_at_risk`, `predicted_duration_days` |
| **Criticality** (`CriticalityScorer`) | Task nào quan trọng nhất (ảnh hưởng lịch dự án)? | TGN memory trên 19,6 triệu sự kiện Jira + readout ranking-aware (3 seed) | `score`, `rank_in_instance`, `is_critical` (top 5%/instance) |

Cả hai được huấn luyện trên The Public Jira Dataset (16 instance, 2.685.911 issue), chia
train/val/test theo thời gian (70/15/15). Số liệu kiểm tra out-of-time nằm trong `manifest.json`
của mỗi bundle (`erd bundle info <bundle>`) và trong `experiments/leaderboard_*.json`.

## Cài đặt

```bash
pip install early-risk-detection            # thư viện suy luận
pip install "early-risk-detection[mongo]"   # + ETL từ MongoDB
pip install -e ".[train,dev]"               # phát triển / huấn luyện lại (từ repo)
```

Yêu cầu Python ≥ 3.10. GPU (CUDA) được dùng nếu có: chấm criticality phải replay toàn bộ dòng
sự kiện (≈1,5 phút trên RTX 4060 Ti cho 2,68 triệu issue), trên CPU chậm hơn nhiều.

## Dùng nhanh

Đầu vào là một DuckDB theo schema của `early_risk_detection.data.etl` (bảng `issues`,
`issue_changelogs`, `issue_links`, `issue_comments`) và embedding văn bản của issue
(`nomic-embed-text` qua Ollama).

```python
from early_risk_detection import CriticalityScorer, DelayRiskScorer
from early_risk_detection.embeddings import EmbeddingIndex, OllamaEmbedder

emb = EmbeddingIndex("data", fallback=OllamaEmbedder())   # embedding có sẵn + Ollama cho issue mới

risk = DelayRiskScorer.load("bundles/delay").score("data/jira.duckdb", embeddings=emb)
crit = CriticalityScorer.load("bundles/criticality").score("data/jira.duckdb", embeddings=emb)

risk[risk.is_at_risk].head()          # issue đang mở có nguy cơ trễ, xếp theo p_delay
crit[crit.is_critical].head()         # top 5% issue quan trọng của mỗi instance
```

Mặc định chấm mọi issue **đang mở tại thời điểm hiện tại**; dùng `as_of=pd.Timestamp(...)` để
chấm tại một mốc khác hoặc `issue_keys=["Apache|SPARK-123", ...]` cho danh sách cụ thể.

CLI tương đương:

```bash
erd etl --instance JFrog --duckdb data/jira.duckdb --overwrite     # MongoDB -> DuckDB
erd embed --duckdb-path data/jira.duckdb --out-dir data             # embedding Ollama cho mọi issue
erd score delay       --bundle bundles/delay       --db data/jira.duckdb --emb-dir data --out risk.csv
erd score criticality --bundle bundles/criticality --db data/jira.duckdb --emb-dir data --out top.csv
erd bundle info bundles/delay
erd eval criticality --track X --pred_file p.csv --ground_truth_file gt.parquet   # harness đánh giá
```

## Cấu trúc repo

```
src/early_risk_detection/     THƯ VIỆN (được đóng gói) — chỉ code cần cho suy luận + đánh giá
  features/t0.py              đặc trưng T0 dùng chung: tái dựng priority/type/assignee lúc tạo,
                              link đã biết tại T0, lịch sử chỉ gồm sự kiện trước T0
  delay/                      features (mô phỏng tải O(N) + featurizer), gate, survival, scorer
  criticality/                stream (dòng sự kiện), memory (TGN), readout, scorer
  data/                       ETL Mongo/JSON -> DuckDB, chuẩn hoá Jira (ex `jira_adapter`)
  embeddings.py               trích xuất Ollama + EmbeddingIndex
  evaluation/                 harness đánh giá delay / criticality
  bundle.py, cli.py
training/                     KHÔNG đóng gói — huấn luyện, import thư viện
  delay/                      build_dataset -> train_xgboost -> train_aft -> train_catboost_survival
                              (none + cause_specific) -> train_non_work -> fit_blend_gate -> export_bundle
  criticality/                build_dataset -> build_events -> train_tgn (+probe_memory) -> train_readout
                              -> evaluate_all -> export_bundle
  */baselines/                mô hình đối chứng của khoá luận (RF, LogReg, Cox, stacking, track 1-5, TGN gốc)
tests/                        pytest (DuckDB tổng hợp, không cần dữ liệu thật)
experiments/                  leaderboard, kết quả; experiments/archive = thí nghiệm cũ (không bảo trì)
docs/                         báo cáo khoá luận, EDA, hình
```

## Huấn luyện lại

```bash
pip install -r requirements-lock.txt && pip install -e . --no-deps
bash training/criticality/run_pipeline.sh       # -> bundles/criticality
PARAMS=1 bash training/delay/run_pipeline.sh    # -> bundles/delay (PARAMS=1: dùng siêu tham số đã tìm)
```

Mỗi bước ghi trạng thái đã fit vào một *staging bundle*; `export_bundle.py` khoá lại thành
bundle có `manifest.json` (phiên bản thư viện, cấu hình, metric test, SHA-256 từng file).
`ModelBundle.load` từ chối bundle bị sửa đổi hoặc khác `kind`.

### Ánh xạ lệnh cũ -> mới

| Trước | Sau |
|---|---|
| `python extract_ollama_embeddings.py` | `erd embed` |
| `python -m jira_adapter.etl ...` | `erd etl ...` (`early_risk_detection.data.etl`) |
| `python evaluation_harness*.py ...` | `erd eval delay|criticality ...` |
| `python prepare_censored_dataset.py`, `tier1_feature_engineering.py` | `training/delay/build_dataset.py` |
| `train_xgboost.py`, `train_survival_aft.py`, `train_catboost_survival.py` | `training/delay/train_{xgboost,aft,catboost_survival}.py` |
| `pre_triage_filter.py` + blend trong `train_catboost_survival.py` | `training/delay/{train_non_work,fit_blend_gate}.py` |
| `tgn_full/*.py` | `training/criticality/*.py` |
| `track1..5_*.py`, `data/build_criticality_ground_truth.py` | `training/criticality/baselines/` |
| `train_rf.py`, `train_logreg.py`, `train_catboost_cox.py`, `stacking_meta_learner.py` | `training/delay/baselines/` |
| `train_self_supervised.py`, `model/`, `modules/`, `utils/` (TGN gốc) | `training/criticality/baselines/tgn_upstream/` |
| `scratch/`, `debug_spring_order.py`, `tgn_full/leakage_demo.py` | `experiments/archive/` |

Mã của nghiên cứu gốc (trước khi tái cấu trúc) nằm ở commit `bff3476`.

## Khác biệt so với kết quả gốc của nghiên cứu

* **Delay**: đặc trưng priority / issuetype / assignee / số link lấy **tại T0** (bản gốc dùng giá
  trị cuối cùng, tức rò rỉ tương lai); nhãn giữ nguyên định nghĩa. Cổng pre-triage được viết lại
  (`delay/gate.py`, `training/delay/train_non_work.py`) vì mã sinh đặc trưng gốc không còn.
  Metric vì vậy khác báo cáo cũ — xem `experiments/leaderboard_delay_t0.json`:

  | Test (346.174 issue) | ROC-AUC | PR-AUC | F1 | Recall |
  |---|---|---|---|---|
  | Gốc (thuộc tính cuối cùng, rò rỉ) — pre_triage | 0,7952 | 0,4860 | 0,5301 | 0,8033 |
  | Mới (T0) — `delay_official_t0` (bundle) | 0,7268 | 0,4139 | 0,4448 | 0,8244 |
  | Mới (T0) — riêng XGBoost | 0,7368 | 0,4177 | 0,4627 | 0,7456 |

  Phần chênh lệch ≈0,07 ROC-AUC là lượng "điểm" mà bản gốc có được nhờ biết giá trị tương lai.
* **Criticality**: sửa lỗi DuckDB `arg_max` khi hoà (thuộc tính T0 không tất định) và trung bình
  back-off chỉ fit trên train. Metric test: NDCG@10 grouped 0,8547 / Precision@Top-5% 0,2386
  (gốc 0,8545 / 0,2390).

## Phát triển

```bash
pytest                    # 17+ test, ~5 giây, không cần GPU / dữ liệu thật
ruff check src tests training
uv build                  # wheel + sdist trong dist/
```

## Giấy phép

Apache-2.0. Phần mô hình TGN dựa trên [twitter-research/tgn](https://github.com/twitter-research/tgn)
(Rossi et al., 2020) — xem `NOTICE`.
