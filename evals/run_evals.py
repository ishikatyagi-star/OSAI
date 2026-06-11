"""
OSAI Eval Runner — scores the Ask OSAI agent against golden fixtures.

Usage:
    uv run python evals/run_evals.py                   # all categories
    uv run python evals/run_evals.py --category ownership
    uv run python evals/run_evals.py --verbose

This is a scaffold for the co-founder (S11). The backend lane (Ishika) will
wire this to the real /ask endpoint and add scoring nuances (semantic similarity,
latency tracking, etc.).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ─── Fixture loading ──────────────────────────────────────────────────────────


def load_fixtures(category: str | None = None) -> list[dict[str, Any]]:
    """Load all fixture files, optionally filtered by category."""
    cases: list[dict[str, Any]] = []
    for f in sorted(FIXTURES_DIR.glob("*.json")):
        with open(f) as fp:
            data = json.load(fp)
        for case in data:
            if category and case.get("category") != category:
                continue
            cases.append(case)
    return cases


# ─── Matching ─────────────────────────────────────────────────────────────────


def check_match(answer: str, expected: str, mode: str) -> bool:
    """Check if the agent answer satisfies the expected value."""
    answer_lower = answer.lower()
    expected_lower = expected.lower()

    if mode == "exact":
        return answer_lower.strip() == expected_lower.strip()
    elif mode == "regex":
        return bool(re.search(expected, answer, re.IGNORECASE))
    else:  # contains (default)
        return expected_lower in answer_lower


# ─── Agent call (stub — replace with real /ask call) ──────────────────────────


def ask_agent(question: str) -> dict[str, Any]:
    """
    Call the Ask OSAI agent. Currently a stub that returns a placeholder.

    TODO (backend lane): replace with:
        import httpx
        resp = httpx.post("http://localhost:8000/ask", json={
            "org_id": os.environ.get("OSAI_DEFAULT_ORG_ID", "demo-org"),
            "question": question
        })
        return resp.json()
    """
    # Stub: return empty so all cases "fail" until the real agent is wired.
    return {
        "answer": "",
        "citations": [],
        "actions_taken": [],
        "latency_ms": 0,
    }


# ─── Runner ───────────────────────────────────────────────────────────────────


def run_evals(category: str | None = None, verbose: bool = False) -> None:
    cases = load_fixtures(category)
    if not cases:
        print(f"No fixtures found{f' for category={category}' if category else ''}.")
        sys.exit(1)

    total = len(cases)
    passed = 0
    failed_cases: list[dict[str, Any]] = []

    print(f"\n{'='*60}")
    print(f"  OSAI Eval Run — {total} cases" + (f" ({category})" if category else ""))
    print(f"{'='*60}\n")

    for case in cases:
        t0 = time.time()
        result = ask_agent(case["question"])
        elapsed_ms = (time.time() - t0) * 1000

        answer = result.get("answer", "")
        match_mode = case.get("match_mode", "contains")
        ok = check_match(answer, case["expected"], match_mode)

        if ok:
            passed += 1
            if verbose:
                print(f"  ✓ [{case['id']}] {case['question'][:60]}")
        else:
            failed_cases.append({**case, "actual": answer, "latency_ms": elapsed_ms})
            if verbose:
                print(f"  ✗ [{case['id']}] {case['question'][:60]}")
                print(f"       expected: {case['expected']}")
                print(f"       actual:   {answer[:80] or '(empty)'}")
                print()

    pass_rate = passed / total if total else 0

    print(f"\n{'─'*60}")
    print(f"  Results: {passed}/{total} passed ({pass_rate:.0%})")
    print(f"{'─'*60}")

    if failed_cases and not verbose:
        print(f"\n  Failed ({len(failed_cases)}):")
        for fc in failed_cases[:10]:
            print(f"    [{fc['id']}] {fc['question'][:50]}…")
            print(f"      expected: {fc['expected']}, got: {fc.get('actual', '')[:40] or '(empty)'}")

    print()
    sys.exit(0 if pass_rate >= 0.8 else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSAI Eval Runner")
    parser.add_argument("--category", type=str, default=None, help="Filter by category")
    parser.add_argument("--verbose", action="store_true", help="Show per-case results")
    args = parser.parse_args()
    run_evals(category=args.category, verbose=args.verbose)
