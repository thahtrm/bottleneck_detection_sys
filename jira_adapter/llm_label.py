"""Gắn nhãn bottleneck bằng LLM — §4.3–4.4 của
`docs/phuong-an-gan-nhan-bottleneck-bang-llm.md`.

LLM (server OpenAI-compatible, vd. LM Studio — cấu hình trong `.env`) đọc hồ sơ
`text/{key}.md` do `sampling.py` sinh, trả JSON theo schema; code:
  1. kiểm tra trích dẫn có thật trong hồ sơ, timestamp episode có trong hồ sơ;
  2. gộp N lần lấy mẫu (đa số cho is_bottleneck/role/type, episode của mẫu
     đồng thuận nhất);
  3. áp rule §4.4 (LLM ∧ F ∧ I kiểm bằng số liệu code) -> final ∈ {1, 0, review}.

Chạy:
    python -m jira_adapter.llm_label --pilot-dir data/llm_pilot/JFrog --limit 5
    python -m jira_adapter.llm_label --pilot-dir data/llm_pilot/JFrog            # toàn bộ, resume được

Ra trong pilot-dir: `llm_raw/{key}.jsonl` (từng lần gọi, dùng để resume),
`llm_labels/{key}.json` (kết quả gộp), `llm_labels.csv`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from .sampling import candidate_reasons

PROMPT_VERSION = "v2"

TYPES = ["dependency", "external", "review", "resource", "requirement", "technical", "process"]
EXCLUSIONS = ["backlog", "epic", "deferred", "duplicate_or_wontfix", "spike", "data_artifact"]

CODEBOOK = """You are a senior software project manager auditing Jira issues. Decide whether an issue was a BOTTLENECK at any point in its life, using ONLY the evidence in the dossier.

DEFINITION
An issue is a bottleneck when it OBSTRUCTED THE FLOW OF WORK *and* its delay AFFECTED others (people, other issues, a release, customers). Slow but nobody waiting = NOT a bottleneck. Many links but progressing normally = NOT a bottleneck.

Bottleneck = (at least one F) AND (at least one I)
F - flow obstruction:
  F1 Stagnation: stuck in an in-progress/committed status much longer than usual (the dossier gives dwell percentiles "pNN" vs. the same status in this project; >= p90 is unusual).
  F2 Explicit waiting: comments/status show it is waiting on someone or something ("waiting for", "blocked by", "pending review", "need input", "on hold").
  F3 Churn/rework: reopened, bouncing between statuses, assignee passed around (>= 3 handoffs).
  F4 Missing capacity: high priority but nobody assigned, or assignee overloaded.
I - impact:
  I1 Blocks others: other OPEN issues depend on it / are blocked by it (chain length raises severity).
  I2 Release critical path: has a fix version, or fix version pushed back repeatedly.
  I3 Escalation: priority raised, many watchers/votes, repeated "any update?" from different people, customers affected.

NOT A BOTTLENECK (exclusions) - set "exclusion":
  backlog: open for a long time, low/normal priority, never started or never committed (nobody working on it). Exception: it blocks other open issues (I1).
  epic: epic/umbrella/tracking issue - long-lived with many links by design.
  deferred: deliberately postponed ("postponed", "deferred to next major", version moved with a stated reason).
  duplicate_or_wontfix: closed as Duplicate / Won't Fix / Cannot Reproduce / Will Not Implement after long being open - forgotten, not stuck.
  spike: research / PoC / investigation task that is long by nature (unless it blocks others).
  data_artifact: the long dwell is caused by bulk closing (flag "bulk_close") or placeholder dates, not by real waiting.
IMPORTANT: Jira priority "Blocker" is a SEVERITY level, NOT evidence of a flow bottleneck.
A large task that keeps progressing with regular updates is NOT a bottleneck.

CONSISTENCY
- If an exclusion clearly applies, answer is_bottleneck = "no" with that exclusion (not "unsure").
- If is_bottleneck = "no" or "unsure": role = "none", type = null, episodes = [].
- If is_bottleneck = "yes": exclusion = null, role is root or victim, at least one F and one I.

ROLE
  root: this issue is the obstruction (others wait for it, or it is stuck itself).
  victim: this issue is stuck mainly because it waits on ANOTHER issue/team (the other one is the root).
  none: not a bottleneck.

TYPE (only if bottleneck): dependency (waits on/blocks another issue), external (customer, vendor, upstream project), review (code review / QA / approval queue), resource (no one available / overloaded / unassigned), requirement (unclear spec, waiting for decision/info), technical (hard technical problem, repeated failed fixes), process (workflow/status queue problem).

EPISODES
If bottleneck, give the period(s) when the issue was obstructed. "start" and "end" MUST be timestamps copied exactly from the dossier (status timeline, change logs or comment times). Use end = null if still obstructed when the data ends.

EVIDENCE RULES
- Every claim needs evidence: copy SHORT exact quotes (5-25 words) from the dossier text. Do not paraphrase inside quotes.
- Do not compute durations yourself; use the numbers given.
- If the evidence is insufficient to decide, answer "unsure". Do not guess.

Answer with ONE JSON object matching the schema. Keep "rationale" to at most 2 sentences."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_bottleneck", "role", "type", "f_criteria", "i_criteria", "waiting_for",
                 "evidence", "episodes", "exclusion", "confidence", "rationale"],
    "properties": {
        "is_bottleneck": {"type": "string", "enum": ["yes", "no", "unsure"]},
        "role": {"type": "string", "enum": ["root", "victim", "none"]},
        "type": {"type": ["string", "null"], "enum": TYPES + [None]},
        "f_criteria": {"type": "array", "items": {"type": "string", "enum": ["F1", "F2", "F3", "F4"]}},
        "i_criteria": {"type": "array", "items": {"type": "string", "enum": ["I1", "I2", "I3"]}},
        "waiting_for": {"type": ["string", "null"]},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "episodes": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["start", "end"],
            "properties": {"start": {"type": "string"}, "end": {"type": ["string", "null"]}}}},
        "exclusion": {"type": ["string", "null"], "enum": EXCLUSIONS + [None]},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
}


# --- cấu hình ---------------------------------------------------------------
def load_env(path: str = ".env") -> dict[str, str]:
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("LLM_")})
    return env


class Client:
    def __init__(self, env: dict[str, str]):
        self.base = env.get("LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/")
        self.key = env.get("LLM_API_KEY", "")
        self.model = env.get("LLM_MODEL", "")
        self.temperature = float(env.get("LLM_TEMPERATURE", "0.7"))
        self.max_tokens = int(env.get("LLM_MAX_TOKENS", "2048"))
        self.timeout = float(env.get("LLM_TIMEOUT_S", "300"))
        # model có reasoning (vd. Qwen3.x): không giới hạn thì suy luận 2–8k token/lần
        # (30–136 s) và hay bị cắt; "low" ≈ 16 s/lần. Để trống = mặc định của server.
        self.reasoning_effort = env.get("LLM_REASONING_EFFORT", "low")
        if not self.model:
            raise SystemExit("LLM_MODEL trống — điền trong .env")

    def chat(self, system: str, user: str) -> dict:
        body = {"model": self.model, "temperature": self.temperature, "max_tokens": self.max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "bottleneck_label", "strict": True, "schema": SCHEMA}}}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        req = urllib.request.Request(f"{self.base}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.key}"})
        t0 = time.time()
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    resp = json.loads(r.read())
                break
            except (urllib.error.URLError, TimeoutError) as ex:
                detail = ex.read().decode("utf-8", "replace") if isinstance(ex, urllib.error.HTTPError) else ""
                if "No models loaded" in detail or "model_not_found" in detail:
                    raise SystemExit(f"LLM server không có model '{self.model}' đang load — "
                                     f"load lại (vd. `lms load {self.model}`) rồi chạy tiếp; "
                                     f"kết quả đã có được giữ trong llm_raw/ và sẽ resume.")
                if attempt == 2:
                    raise
                print(f"  ! lỗi gọi LLM ({ex}), thử lại", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        ch = resp["choices"][0]
        return {"content": ch["message"].get("content") or "", "finish_reason": ch.get("finish_reason"),
                "usage": resp.get("usage"), "seconds": round(time.time() - t0, 1)}


# --- kiểm tra & gộp ------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def parse_answer(content: str) -> dict | None:
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _quote_found(q: str, nt: str) -> bool:
    """Trích dẫn có trong hồ sơ? Chấp nhận tiền tố nhãn do LLM thêm ("Status: …")
    và khớp gần đúng: đoạn liên tục dài nhất ≥ 80% độ dài trích dẫn."""
    from difflib import SequenceMatcher
    nq = _norm(q).strip(' ."…\'')
    if not nq:
        return True
    if nq in nt:
        return True
    m = re.match(r"^[\w\s/-]{1,25}:\s*(.+)$", nq)
    if m and m.group(1) in nt:
        return True
    sm = SequenceMatcher(None, nq, nt, autojunk=False)
    return sm.find_longest_match(0, len(nq), 0, len(nt)).size >= 0.8 * len(nq)


def verify(ans: dict, text: str) -> dict:
    """Đánh dấu trích dẫn / timestamp không có thật trong hồ sơ."""
    nt = _norm(text)
    quotes = ans.get("evidence") or []
    bad_q = [q for q in quotes if not _quote_found(q, nt)]
    stamps = set(re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text))
    bad_t = [t for ep in ans.get("episodes") or [] for t in (ep.get("start"), ep.get("end"))
             if t is not None and t not in stamps]
    return {"n_quotes": len(quotes), "bad_quotes": bad_q, "bad_timestamps": bad_t}


def _iou(a: list[dict], b: list[dict], end_default: str) -> float:
    def ivs(eps):
        return [(e["start"], e["end"] or end_default) for e in eps if e.get("start")]
    A, B = ivs(a), ivs(b)
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    from datetime import datetime
    def ts(s):
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    inter = sum(max(0.0, min(ts(e1), ts(e2)) - max(ts(s1), ts(s2))) for s1, e1 in A for s2, e2 in B)
    union = sum(ts(e) - ts(s) for s, e in A) + sum(ts(e) - ts(s) for s, e in B) - inter
    return inter / union if union > 0 else 1.0


def aggregate(samples: list[dict], dossier: dict) -> dict:
    """Gộp N mẫu hợp lệ + rule §4.4."""
    valid = [s for s in samples if s.get("answer")]
    if not valid:
        return {"final": "review", "reason": "no_valid_answer", "n_valid": 0}
    vote = Counter(s["answer"]["is_bottleneck"] for s in valid)
    top, n_top = vote.most_common(1)[0]
    majority = top if n_top * 2 > len(valid) else "unsure"
    agree = [s for s in valid if s["answer"]["is_bottleneck"] == majority] or valid
    role = Counter(s["answer"]["role"] for s in agree).most_common(1)[0][0]
    typ = Counter(s["answer"]["type"] for s in agree).most_common(1)[0][0]
    excl = Counter(s["answer"]["exclusion"] for s in agree).most_common(1)[0][0]
    # episode: mẫu có tổng IoU lớn nhất với các mẫu đồng thuận còn lại (medoid)
    end_default = dossier["data_end"]
    best = max(agree, key=lambda s: sum(_iou(s["answer"]["episodes"], o["answer"]["episodes"], end_default)
                                        for o in agree if o is not s))
    f_llm = sorted({c for s in agree for c in s["answer"]["f_criteria"]})
    i_llm = sorted({c for s in agree for c in s["answer"]["i_criteria"]})
    fabricated = sum(len(s["check"]["bad_quotes"]) + len(s["check"]["bad_timestamps"]) for s in agree)

    # kiểm F/I bằng số liệu code (§4.4)
    sig = dossier["signals"]
    f_code = candidate_reasons(dossier)
    f_ok = bool(f_code) or ("F2" in f_llm and not best["check"]["bad_quotes"])
    i_code = []
    if sig["I1_block_depend_links"] > 0:
        i_code.append("I1")
    if sig["I2_fixversion_changes"] > 0 or dossier["fix_versions"]:
        i_code.append("I2")
    if sig["I3_priority_raised"] > 0 or sig["I3_watchers"] >= 5 or sig["I3_votes"] >= 3:
        i_code.append("I3")
    i_ok = bool(i_code) or ("I3" in i_llm and not best["check"]["bad_quotes"])

    if majority == "yes" and excl is None and f_ok and i_ok and role != "none":
        final, reason = 1, "llm_yes_and_rule_ok"
    elif majority == "no" or (majority == "yes" and excl is not None):
        final, reason = 0, "llm_no" if majority == "no" else f"excluded:{excl}"
    elif majority == "yes":
        final, reason = "review", f"rule_fail(F={f_ok},I={i_ok},role={role})"
    else:
        final, reason = "review", "llm_unsure_or_split"
    if final != "review" and fabricated:
        final, reason = "review", f"{reason};fabricated_evidence={fabricated}"

    return {"final": final, "reason": reason, "n_valid": len(valid),
            "vote": dict(vote), "majority": majority, "role": role, "type": typ, "exclusion": excl,
            "f_llm": f_llm, "i_llm": i_llm, "f_code": f_code, "i_code": i_code,
            "episodes": best["answer"]["episodes"], "evidence": best["answer"]["evidence"],
            "waiting_for": best["answer"]["waiting_for"], "rationale": best["answer"]["rationale"],
            "confidence": round(sum(s["answer"]["confidence"] for s in agree) / len(agree), 2),
            "fabricated_evidence": fabricated}


# --- chạy -------------------------------------------------------------------
def label_issue(client: Client, key: str, pilot: Path, n_samples: int) -> dict:
    text = (pilot / "text" / f"{key}.md").read_text(encoding="utf-8")
    dossier = json.loads((pilot / "dossiers" / f"{key}.json").read_text(encoding="utf-8"))
    raw_path = pilot / "llm_raw" / f"{key}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    if raw_path.exists():
        samples = [json.loads(l) for l in raw_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        samples = [s for s in samples if s.get("prompt_version") == PROMPT_VERSION
                   and s.get("model") == client.model]
    user = f"DOSSIER\n\n{text}\n\nReturn the JSON object now."
    # mẫu bị cắt (hết max_tokens khi reasoning) / JSON hỏng không tính; tối đa 2N lần gọi mới
    n_calls = 0
    while sum(1 for s in samples if s.get("answer")) < n_samples and n_calls < 2 * n_samples:
        n_calls += 1
        r = client.chat(CODEBOOK, user)
        ans = parse_answer(r["content"])
        s = {"prompt_version": PROMPT_VERSION, "model": client.model, **r, "answer": ans,
             "check": verify(ans, text) if ans else None}
        with raw_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
        samples.append(s)
    agg = aggregate(samples, dossier)
    agg.update({"key": key, "model": client.model, "prompt_version": PROMPT_VERSION,
                "seconds": round(sum(s["seconds"] for s in samples), 1),
                "tokens": sum((s.get("usage") or {}).get("total_tokens", 0) for s in samples),
                "truncated": sum(1 for s in samples if s.get("finish_reason") == "length")})
    out = pilot / "llm_labels" / f"{key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, ensure_ascii=False, indent=1), encoding="utf-8")
    return agg


CSV_COLS = ["key", "tier", "final", "reason", "majority", "vote", "role", "type", "exclusion",
            "f_llm", "i_llm", "f_code", "i_code", "episodes", "confidence", "fabricated_evidence",
            "truncated", "seconds", "tokens"]


def write_csv(pilot: Path, manifest: dict[str, dict]) -> Path:
    rows = []
    for p in sorted((pilot / "llm_labels").glob("*.json")):
        a = json.loads(p.read_text(encoding="utf-8"))
        a["tier"] = manifest.get(a["key"], {}).get("tier")
        rows.append({c: (json.dumps(a.get(c), ensure_ascii=False) if isinstance(a.get(c), (list, dict))
                         else a.get(c)) for c in CSV_COLS})
    path = pilot / "llm_labels.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir", required=True)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--limit", type=int, default=None, help="chỉ chạy N issue đầu (xen kẽ các tầng)")
    ap.add_argument("--keys", nargs="*", default=None)
    ap.add_argument("--n-samples", type=int, default=None)
    args = ap.parse_args()

    env = load_env(args.env)
    client = Client(env)
    n_samples = args.n_samples or int(env.get("LLM_N_SAMPLES", "3"))
    pilot = Path(args.pilot_dir)
    with (pilot / "manifest.csv").open(encoding="utf-8") as fh:
        manifest = {r["key"]: r for r in csv.DictReader(fh)}

    if args.keys:
        keys = args.keys
    else:
        import random
        by_tier: dict[str, list[str]] = {}
        for k, r in manifest.items():
            by_tier.setdefault(r["tier"], []).append(k)
        for v in by_tier.values():  # manifest xếp theo tầng con (mở trước) -> xáo để --limit đại diện
            random.Random(0).shuffle(v)
        keys = []  # xen kẽ các tầng để mẫu nhỏ vẫn đủ loại
        for i in range(max(len(v) for v in by_tier.values())):
            keys += [v[i] for v in by_tier.values() if i < len(v)]
    if args.limit:
        keys = keys[: args.limit]

    t0 = time.time()
    for i, k in enumerate(keys, 1):
        a = label_issue(client, k, pilot, n_samples)
        print(f"[{i}/{len(keys)}] {k:<16} tier={manifest[k]['tier']:<9} final={a['final']!s:<6} "
              f"vote={a.get('vote')} role={a.get('role')} type={a.get('type')} excl={a.get('exclusion')} "
              f"fab={a.get('fabricated_evidence')} trunc={a.get('truncated')} {a.get('seconds')}s "
              f"| elapsed {time.time() - t0:.0f}s", flush=True)
    print(write_csv(pilot, manifest))


if __name__ == "__main__":
    main()
