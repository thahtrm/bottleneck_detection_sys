# Báo cáo so sánh: TGN Multiple-Head vs Classical Baselines

**Trạng thái:** complete · **Repo tip:** `PLACEHOLDER`  
**Protocol:** Q1=B′ (primary snapshots `T0_pre` / `T3_change` / `T7_change` / `T_active_change`), Q2–Q8=A  
**Models có số liệu:** `dual_tgn`, `logreg`, `rf`, `xgb`  
**Leaderboard:** `experiments/leaderboard_multihead_vs_classical.json`

## 1. Tóm tắt điều hành

- **Tổng thể (@T0_pre):** Không có model đơn thắng cả hai head tại `@T0_pre` (Delay: `rf`, Criticality: `dual_tgn`).
- **Head Delay Risk:** `rf` (PR-AUC=0.4226 @T0_pre)
- **Head Criticality:** `dual_tgn` (NDCG@10 Grouped=0.8551 @T0_pre)
- **Post-T0:** Dual-Head dùng memory `z` động; classical dùng T0 base ⊕ **as-of tabular** (không có `z`).
- **@T_active_change:** cả Dual-Head và classical mạnh hơn T0 trên Delay PR-AUC; Dual-Head dẫn Prec@Top-5% (P0).

## 2. Protocol đã khóa

| Q | Quyết định |
|---|---|
| Q1 | **B′** — primary = `T0_pre` + `T3_change` + `T7_change` + `T_active_change` (cả Dual-Head và classical) |
| Q2 | A — không full retrain Dual-Head; re-eval checkpoint/CSV + MAE mean |
| Q3 | A — shared `X_xgb_*` (264) cho delay LR/RF/XGB |
| Q4 | A — duration regressors cho MAE |
| Q5 | A — regress `ground_truth_criticality` rồi rank |
| Q6 | A — bảng chính chỉ Dual-Head + LR/RF/XGB |
| Q7 | A — val sweep Recall≥0.80 ưu tiên; fallback Max-F1; báo cả hai |
| Q8 | A — full 16 ecosystems (`tgn_full_v2`) |

### Snapshot naming (repo)

- **`T0_pre`:** Pre-create / pre-T0 memory snapshot (horizon_days=-1)
- **`T3_change`:** Latest active (non-closing) event within 3 days of T0
- **`T7_change`:** Latest active (non-closing) event within 7 days of T0
- **`T_active_change`:** Latest active event before resolution (horizon_days=None); repo name for in-progress / currently-active project-change snapshot

## 3. Bảng kết quả theo snapshot

### `T0_pre`

_Pre-create / pre-T0 memory snapshot (horizon_days=-1)_

#### Task Delay Risk

| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |
|---|---:|---:|---:|---:|---:|---|
| `dual_tgn` | 0.7443 | 0.4109 | 0.7812 | 82.91 | 14.23 | `val_recall_ge_0.80` |
| `logreg` | 0.6969 | 0.3738 | 0.7259 | 92.67 | 50.72 | `val_recall_ge_0.80` |
| `rf` | 0.7380 | 0.4226 | 0.8114 | 164.58 | 159.46 | `val_recall_ge_0.80` |
| `xgb` | 0.7371 | 0.4178 | 0.7794 | 69.13 | 49.30 | `val_recall_ge_0.80` |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.8719 | 0.8551 | 0.2417 | 4184/17309 |
| `logreg` | 0.9220 | 0.8449 | 0.2030 | 3514/17309 |
| `rf` | 0.7842 | 0.8465 | 0.1956 | 3385/17309 |
| `xgb` | 0.2934 | 0.8501 | 0.2095 | 3626/17309 |

### `T3_change`

_Latest active (non-closing) event within 3 days of T0_

#### Task Delay Risk

| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |
|---|---:|---:|---:|---:|---:|---|
| `dual_tgn` | 0.7848 | 0.4627 | 0.7651 | 117.77 | 9.66 | `val_recall_ge_0.80` |
| `logreg` | 0.7058 | 0.3892 | 0.7078 | 92.67 | 50.72 | `val_recall_ge_0.80` |
| `rf` | 0.7508 | 0.4469 | 0.7639 | 164.58 | 159.46 | `val_recall_ge_0.80` |
| `xgb` | 0.7549 | 0.4511 | 0.7312 | 69.13 | 49.30 | `val_recall_ge_0.80` |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.8524 | 0.8689 | 0.2863 | 4956/17309 |
| `logreg` | 0.9528 | 0.8567 | 0.2271 | 3931/17309 |
| `rf` | 0.9927 | 0.8669 | 0.2492 | 4314/17309 |
| `xgb` | 0.9819 | 0.8777 | 0.2735 | 4734/17309 |

### `T7_change`

_Latest active (non-closing) event within 7 days of T0_

#### Task Delay Risk

| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |
|---|---:|---:|---:|---:|---:|---|
| `dual_tgn` | 0.7917 | 0.4746 | 0.7543 | 108.09 | 8.40 | `val_recall_ge_0.80` |
| `logreg` | 0.7054 | 0.3903 | 0.7052 | 92.67 | 50.72 | `val_recall_ge_0.80` |
| `rf` | 0.7599 | 0.4610 | 0.7925 | 164.58 | 159.46 | `val_recall_ge_0.80` |
| `xgb` | 0.7619 | 0.4645 | 0.7138 | 69.13 | 49.30 | `val_recall_ge_0.80` |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.8516 | 0.8708 | 0.2923 | 5059/17309 |
| `logreg` | 0.9544 | 0.8579 | 0.2284 | 3954/17309 |
| `rf` | 0.9956 | 0.8699 | 0.2533 | 4384/17309 |
| `xgb` | 0.9891 | 0.8806 | 0.2808 | 4861/17309 |

### `T_active_change`

_Latest active event before resolution (horizon_days=None); repo name for in-progress / currently-active project-change snapshot_

#### Task Delay Risk

| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |
|---|---:|---:|---:|---:|---:|---|
| `dual_tgn` | 0.9263 | 0.8470 | 0.8082 | 103.27 | 5.47 | `val_recall_ge_0.80` |
| `logreg` | 0.8809 | 0.8293 | 0.8195 | 92.67 | 50.72 | `val_recall_ge_0.80` |
| `rf` | 0.9224 | 0.8772 | 0.8088 | 164.58 | 159.46 | `val_recall_ge_0.80` |
| `xgb` | 0.9247 | 0.8788 | 0.7962 | 69.13 | 49.30 | `val_recall_ge_0.80` |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.9189 | 0.9217 | 0.4867 | 8425/17309 |
| `logreg` | 0.9972 | 0.9230 | 0.3965 | 6863/17309 |
| `rf` | 0.9969 | 0.9449 | 0.4579 | 7925/17309 |
| `xgb` | 0.9941 | 0.9446 | 0.4447 | 7698/17309 |

## 4. Hạn chế

- Classical post-T0 **không** nhận TGN memory `z` (Dual-Head-only); chỉ as-of tabular + T0 base.
- RF/LR train có subsample để chạy được trên ~1.6M rows; XGB dùng params Optuna sẵn có khi có.
- MAE classical lấy từ duration regressor train @T0 (nhãn duration không phụ thuộc snapshot).
- Threshold Delay primary theo val; phân bố val/test lệch có thể làm Recall test < 0.80 dù val đạt.

## 5. Khuyến nghị

- Giữ **Dual-Head** làm default production nếu nó thắng PR-AUC delay và NDCG@10 Grouped / Prec@Top-5% trên `@T0_pre`, và rõ ràng hơn tại `@T_active_change`.
- Tabular LR/RF/XGB phù hợp khi cần latency/ops đơn giản **tại T0**; không kỳ vọng theo kịp Dual-Head khi có tín hiệu in-progress (`T_active_change`) nếu thiếu as-of/event features mạnh.
- Không đổi bundle `:8000` cho đến khi bảng classical đủ và review OK.
