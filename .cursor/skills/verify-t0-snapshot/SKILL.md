---
name: verify-t0-snapshot
description: "Check that criticality memory snapshots freeze before any event at or after an issue's creation time. Use when editing snapshot_memory, EventStream, or the T0 cutoff in src/early_risk_detection/criticality/memory.py."
---

# Verify the T0 memory snapshot

A criticality score is the model's view of an issue at the moment it was created. `snapshot_memory` replays the event stream in chunks and freezes each issue's memory before the first chunk whose last timestamp is at or after that issue's `created_ts`. If a later or same-time event is included, the score has seen the future, and a high rank is not an early warning.

This repo has no SMT verifier, model checker, or proof assistant in its dependencies, and Python has no such tool installed for this checkout. The check therefore runs the real `snapshot_memory` on generated time-sorted streams and compares it to an independent loop that stops at the first chunk whose last timestamp is greater than or equal to `created_ts`. It also requires the returned applied timestamp to be strictly earlier than `created_ts`.

## When a change touches this

The covered code is `snapshot_memory` and `EventStream` in `src/early_risk_detection/criticality/memory.py` (the chunk cutoff uses the last timestamp of each chunk, and the snapshot is taken with `searchsorted(..., side="left")`).

Last confirmed at commit `9158183a0af14af62cd833d41d00ebdc3f2d79cc`. If `memory.py` differs from that commit, the check can still run, but a pass does not mean the verification still describes the new code. Re-read the function, and move the commit recorded above forward only after you confirm the script still describes the cutoff the code implements.

## Run

From the repo root, with the project venv:

```bash
.venv/bin/python .cursor/skills/verify-t0-snapshot/check_snapshot_before_t0.py
```

Exit 0 prints `PASS` and the case count. Exit 1 prints `FAIL` and one counterexample: the issue's `created_ts`, the chunk size, the event timestamps, the applied timestamp the function returned, and the timestamp the independent loop expected. A failure is a bug until the code and this script are shown to describe different steps. Do not edit the expected cutoff so the run goes green. Do not change product code unless the user asks.

## What a pass covers

- Time-sorted streams of 0 to 30 events, chunk sizes from 1 up to the stream length, and issue creation times that fall before the first event, on a chunk boundary, inside a chunk, and after the last event, including ties.
- 12 fixed boundary streams plus 80 streams from seed 0.
- The real `TGNMemory` and `EventStream` on CPU. Node ids stay inside the memory table so a crash is a failure of the run, not a skipped case.

## What a pass does not cover

- Streams that are not sorted by time. `EventStream` treats the last timestamp in a chunk as that chunk's maximum, which is true only when timestamps are non-decreasing. The event builder sorts; this check does not excuse an unsorted memmap.
- Whether the memory vector's values are correct. Only the cutoff timestamp is checked.
- `history_before` in `src/early_risk_detection/features/t0.py`, which drops same-second history for tabular T0 features. That is a second cutoff, not this one.
- The full 19.6 million event Jira replay.

## Tell a modeling miss from a bug

The script's loop and `snapshot_memory` must agree, and the applied timestamp must be strictly before `created_ts` (or absent, when no earlier chunk exists). If they disagree, the function applied a different chunk than "stop at the first chunk whose last timestamp is at or after creation". That is the bug. If the script crashes before printing `PASS` or `FAIL`, the stream fixture is wrong; fix the script, then rerun. A green run after loosening `>=` to `>` in the script is not a pass.
