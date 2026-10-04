# EDA The Public Jira Dataset

Number of instances analysed: **1**

## Mojang
- Issues: **50,000** (mở: 3,238)
- Khoảng thời gian issue: 2014-01-25 → 2022-01-05
- Events: **210,411** (trung vị 3.0/issue) — phân bố: status:97,550, comment:87,054, link:24,492, assignee:1,015, priority:300
- Links: 40,227 endpoint-occurrences (≈ 20,113 link độc lập — mỗi link xuất hiện trong document của cả 2 issue); % issue có Block/Depend: **0.03%**; % issue có ≥1 link bất kỳ: 50.55%
  - Theo loại chuẩn: Duplicate:38,740, Relate:1,450, Other:23, Block:14
- Assignees: 20 người; % issue có assignee: 1.37%
- Comments: 87,054 (trung vị 1.0/issue)
- Status top: Resolved:46,762, Open:2,496, Reopened:742

## Gợi ý quyết định P1 (từ số liệu)
- **Mojang**: 210,411 events → nhẹ — chạy được CPU lẫn GPU, phù hợp sanity
