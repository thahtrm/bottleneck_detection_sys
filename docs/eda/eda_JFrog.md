# EDA The Public Jira Dataset

Number of instances analysed: **1**

## JFrog
- Issues: **15,535** (mở: 5,191)
- Khoảng thời gian issue: 2006-10-04 → 2022-01-04
- Events: **55,666** (trung vị 3.0/issue) — phân bố: status:31,703, comment:13,152, assignee:6,771, link:2,125, priority:1,915
- Links: 4,250 endpoint-occurrences (≈ 2,125 link độc lập — mỗi link xuất hiện trong document của cả 2 issue); % issue có Block/Depend: **3.01%**; % issue có ≥1 link bất kỳ: 21.04%
  - Theo loại chuẩn: Relate:1,822, Duplicate:1,380, Depend:538, Trigger:410, Incorporate:98, Other:2
- Assignees: 184 người; % issue có assignee: 60.91%
- Comments: 13,152 (trung vị 0.0/issue)
- Status top: Done:6,344, Open:4,997, Closed:2,455, Resolved:1,545, Backlog:77

## Gợi ý quyết định P1 (từ số liệu)
- **JFrog**: 55,666 events → nhẹ — chạy được CPU lẫn GPU, phù hợp sanity
