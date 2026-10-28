"""Runs evals/cases.json against a live endpoint and writes evals/results.md.

usage: AGENT_API_KEY=... python evals/run_evals.py [base_url]
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
# ponytail: stopword counting, good enough to tell spanish from english in short answers
ES_WORDS = {"el", "la", "los", "las", "de", "del", "que", "y", "en", "es", "su", "con", "por", "para", "una", "puedo"}
EN_WORDS = {"the", "and", "is", "of", "to", "in", "he", "his", "with", "for", "has", "was", "can", "i"}


def ask(base_url: str, key: str, case: dict) -> dict:
    body = json.dumps({"model": "cv-agent", "input": case["input"]}).encode()
    req = urllib.request.Request(
        f"{base_url}/responses",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    # free tier quota runs out fast, so wait and retry a couple of times on 429
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            time.sleep(30)


def detect_lang(text: str) -> str:
    words = [w.strip(".,;:!?¿¡()\"'*").lower() for w in text.split()]
    es = sum(w in ES_WORDS for w in words)
    en = sum(w in EN_WORDS for w in words)
    return "es" if es > en else "en"


def check(case: dict, text: str) -> list[str]:
    low = text.lower()
    fails = [f"missing '{s}'" for s in case.get("all", []) if s.lower() not in low]
    if case.get("any") and not any(s.lower() in low for s in case["any"]):
        fails.append(f"none of {case['any']}")
    fails += [f"contains '{s}'" for s in case.get("none", []) if s.lower() in low]
    if case.get("lang") and detect_lang(text) != case["lang"]:
        fails.append(f"answered in {detect_lang(text)}, expected {case['lang']}")
    return fails


def write_report(base_url: str, rows: list[dict]) -> None:
    passed = sum(not r["fails"] for r in rows)
    total_by_cat = Counter(r["category"] for r in rows)
    passed_by_cat = Counter(r["category"] for r in rows if not r["fails"])
    models = Counter(r["model"] for r in rows)
    lines = [
        "# Eval results",
        "",
        f"Run: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC against `{base_url}`",
        f"Models used: {', '.join(f'{m} ({n})' for m, n in models.items())}",
        "",
        f"**Pass rate: {passed}/{len(rows)} ({passed / len(rows):.0%})**",
        "",
        "| Category | Passed |",
        "|---|---|",
    ]
    lines += [f"| {c} | {passed_by_cat[c]}/{n} |" for c, n in total_by_cat.items()]
    lines += ["", "| Case | Category | Result | Latency |", "|---|---|---|---|"]
    for r in rows:
        result = "pass" if not r["fails"] else "FAIL: " + "; ".join(r["fails"]).replace("|", "/")
        lines.append(f"| {r['id']} | {r['category']} | {result} | {r['latency']:.1f}s |")
    lines += ["", "## Answers", ""]
    for r in rows:
        question = r["input"] if isinstance(r["input"], str) else r["input"][-1]["content"]
        answer = r["text"].replace("\n", "\n> ")
        lines += [f"### {r['id']}", "", f"**Q:** {question}", "", f"> {answer}", ""]
    (HERE / "results.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000/v1"
    key = os.environ["AGENT_API_KEY"]
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        start = time.time()
        try:
            body = ask(base_url, key, case)
        except (urllib.error.URLError, TimeoutError) as e:
            # one broken request shouldn't throw away the rest of the run
            rows.append({**case, "text": "", "fails": [f"request failed: {e}"], "latency": time.time() - start, "model": "none"})
            print(f"FAIL {case['id']} request failed: {e}")
            continue
        latency = time.time() - start
        text = "".join(
            part["text"] for item in body["output"] if item["type"] == "message" for part in item["content"]
        )
        fails = check(case, text)
        rows.append({**case, "text": text, "fails": fails, "latency": latency, "model": body["model"]})
        print(f"{'ok  ' if not fails else 'FAIL'} {case['id']} {'; '.join(fails)}")
    write_report(base_url, rows)
    passed = sum(not r["fails"] for r in rows)
    print(f"\n{passed}/{len(rows)} passed, report in evals/results.md")
    sys.exit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    main()
