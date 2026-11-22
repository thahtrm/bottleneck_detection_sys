# Báo cáo so sánh: TGN Multiple-Head vs Classical Baselines

**Trạng thái:** partial/complete tùy leaderboard · **Repo tip:** `662f1f62c34fcfea2c79c6c610005cb2384d3579`  
**Protocol:** Q1=B′ (primary snapshots `T0_pre` / `T3_change` / `T7_change` / `T_active_change`), Q2–Q8=A  
**Models có số liệu:** `dual_tgn`  
**Leaderboard:** `experiments/leaderboard_multihead_vs_classical.json`

## 1. Tóm tắt điều hành

- **Tổng thể (@T0_pre):** pending (cần đủ classical + Dual-Head trên cả hai head)
- **Head Delay Risk:** `dual_tgn` (PR-AUC=0.4109 @T0_pre)
- **Head Criticality:** `dual_tgn` (NDCG@10 Grouped=0.8551 @T0_pre)
- **Post-T0:** Dual-Head dùng memory `z` động; classical dùng T0 base ⊕ **as-of tabular** (không có `z`).

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
| `logreg` | — | — | — | — | — | pending |
| `rf` | — | — | — | — | — | pending |
| `xgb` | — | — | — | — | — | pending |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.8719 | 0.8551 | 0.2417 | 4184/17309 |
| `logreg` | — | — | — | — |
| `rf` | — | — | — | — |
| `xgb` | — | — | — | — |

### `T3_change`

_Latest active (non-closing) event within 3 days of T0_

#### Task Delay Risk

| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |
|---|---:|---:|---:|---:|---:|---|
| `dual_tgn` | 0.7848 | 0.4627 | 0.7651 | 117.77 | 9.66 | `val_recall_ge_0.80` |
| `logreg` | — | — | — | — | — | pending |
| `rf` | — | — | — | — | — | pending |
| `xgb` | — | — | — | — | — | pending |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.8524 | 0.8689 | 0.2863 | 4956/17309 |
| `logreg` | — | — | — | — |
| `rf` | — | — | — | — |
| `xgb` | — | — | — | — |

### `T7_change`

_Latest active (non-closing) event within 7 days of T0_

#### Task Delay Risk

| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |
|---|---:|---:|---:|---:|---:|---|
| `dual_tgn` | 0.7917 | 0.4746 | 0.7543 | 108.09 | 8.40 | `val_recall_ge_0.80` |
| `logreg` | — | — | — | — | — | pending |
| `rf` | — | — | — | — | — | pending |
| `xgb` | — | — | — | — | — | pending |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.8516 | 0.8708 | 0.2923 | 5059/17309 |
| `logreg` | — | — | — | — |
| `rf` | — | — | — | — |
| `xgb` | — | — | — | — |

### `T_active_change`

_Latest active event before resolution (horizon_days=None); repo name for in-progress / currently-active project-change snapshot_

#### Task Delay Risk

| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |
|---|---:|---:|---:|---:|---:|---|
| `dual_tgn` | 0.9263 | 0.8470 | 0.8082 | 103.27 | 5.47 | `val_recall_ge_0.80` |
| `logreg` | — | — | — | — | — | pending |
| `rf` | — | — | — | — | — | pending |
| `xgb` | — | — | — | — | — | pending |

#### Task Criticality

| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |
|---|---:|---:|---:|---|
| `dual_tgn` | 0.9189 | 0.9217 | 0.4867 | 8425/17309 |
| `logreg` | — | — | — | — |
| `rf` | — | — | — | — |
| `xgb` | — | — | — | — |

## 4. Hạn chế

- Classical post-T0 **không** nhận TGN memory `z` (Dual-Head-only); chỉ as-of tabular + T0 base.
- RF/LR train có subsample để chạy được trên ~1.6M rows; XGB dùng params Optuna sẵn có khi có.
- MAE classical lấy từ duration regressor train @T0 (nhãn duration không phụ thuộc snapshot).
- Threshold Delay primary theo val; phân bố val/test lệch có thể làm Recall test < 0.80 dù val đạt.

## 5. Khuyến nghị

- Giữ **Dual-Head** làm default production nếu nó thắng PR-AUC delay và NDCG@10 Grouped / Prec@Top-5% trên `@T0_pre`, và rõ ràng hơn tại `@T_active_change`.
- Tabular LR/RF/XGB phù hợp khi cần latency/ops đơn giản **tại T0**; không kỳ vọng theo kịp Dual-Head khi có tín hiệu in-progress (`T_active_change`) nếu thiếu as-of/event features mạnh.
- Không đổi bundle `:8000` cho đến khi bảng classical đủ và review OK.
