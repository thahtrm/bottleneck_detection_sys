# EDA The Public Jira Dataset

Number of instances analysed: **1**

## Spring
- Issues: **69,156** (mở: 7,594)
- Khoảng thời gian issue: 2003-11-26 → 2021-12-22
- Events: **372,553** (trung vị 4.0/issue) — phân bố: comment:186,077, status:128,673, assignee:41,288, link:11,053, priority:5,462
- Links: 22,092 endpoint-occurrences (≈ 11,046 link độc lập — mỗi link xuất hiện trong document của cả 2 issue); % issue có Block/Depend: **4.04%**; % issue có ≥1 link bất kỳ: 20.51%
  - Theo loại chuẩn: Relate:13,966, Duplicate:3,580, Depend:3,565, Supercede:981
- Assignees: 260 người; % issue có assignee: 89.8%
- Comments: 186,077 (trung vị 2.0/issue)
- Status top: Closed:37,200, Resolved:21,217, Open:6,225, Done:3,145, To Do:664

## Gợi ý quyết định P1 (từ số liệu)
- **Spring**: 372,553 events → nhẹ — chạy được CPU lẫn GPU, phù hợp sanity
