#!/usr/bin/env python3
"""
detect_disagreements.py — Parse 3 reviewer outputs and surface meaningful disagreements.

Reads:
  task2_neofirm/workspace/reviews/market_review.md
  task2_neofirm/workspace/reviews/technology_review.md
  task2_neofirm/workspace/reviews/business_review.md

Writes:
  task2_neofirm/workspace/committee/disagreements.json  (machine-readable)
  stdout: markdown summary for Claude Code to read
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent / "workspace"
REVIEWS_DIR = WORKSPACE / "reviews"
COMMITTEE_DIR = WORKSPACE / "committee"

REVIEW_FILES = {
    "market": REVIEWS_DIR / "market_review.md",
    "technology": REVIEWS_DIR / "technology_review.md",
    "business": REVIEWS_DIR / "business_review.md",
}

CRITERIA = [
    "problem_severity",
    "customer_evidence",
    "market_opportunity",
    "differentiation",
    "technical_feasibility",
    "execution_feasibility",
    "business_model",
    "scalability",
    "risk",
    "evidence_quality",
]


def extract_scores(text: str) -> dict[str, int]:
    """Extract criterion: score pairs from review markdown."""
    scores: dict[str, int] = {}
    # Match patterns like "problem_severity: 4", "Problem Severity: 4/5", "| Problem Severity | 4 |"
    for criterion in CRITERIA:
        # Try various formats
        display = criterion.replace("_", " ")
        patterns = [
            rf"{re.escape(criterion)}\s*[:|]\s*(\d)",
            rf"{re.escape(display)}\s*[:|]\s*(\d)",
            rf"\|\s*{re.escape(display)}\s*\|\s*(\d)\s*\|",
            rf"\|\s*{re.escape(criterion)}\s*\|\s*(\d)\s*\|",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                if 1 <= val <= 5:
                    scores[criterion] = val
                break
    return scores


def extract_decision(text: str) -> str:
    """Extract INVEST / HOLD / PASS decision."""
    m = re.search(r"\b(INVEST|HOLD|PASS)\b", text, re.IGNORECASE)
    return m.group(1).upper() if m else "UNKNOWN"


def detect_disagreements(
    scores: dict[str, dict[str, int]],
    decisions: dict[str, str],
) -> list[dict]:
    """Return list of disagreement records."""
    disagreements: list[dict] = []

    # Different final decisions
    decision_values = list(decisions.values())
    if len(set(decision_values)) > 1:
        disagreements.append({
            "id": "D00",
            "type": "decision",
            "issue": "Reviewers reached different final decisions",
            "reviewer_positions": decisions,
            "severity": "HIGH",
            "why_it_matters": "A split decision requires committee deliberation before a recommendation can be made.",
        })

    # Score gaps >= 2 on any criterion
    reviewer_names = list(scores.keys())
    for criterion in CRITERIA:
        vals = {r: scores[r].get(criterion) for r in reviewer_names if scores[r].get(criterion) is not None}
        if len(vals) < 2:
            continue
        score_list = list(vals.values())
        gap = max(score_list) - min(score_list)
        if gap >= 2:
            disagreements.append({
                "id": f"D{len(disagreements):02d}",
                "type": "score_gap",
                "criterion": criterion,
                "issue": f"Score gap of {gap} on '{criterion.replace('_', ' ')}'",
                "reviewer_positions": vals,
                "severity": "HIGH" if gap >= 3 else "MEDIUM",
                "why_it_matters": f"A {gap}-point spread on {criterion.replace('_', ' ')} suggests reviewers weighed different evidence or made conflicting assumptions.",
            })

    return disagreements


def format_markdown(
    decisions: dict[str, str],
    scores: dict[str, dict[str, int]],
    disagreements: list[dict],
) -> str:
    lines = ["# Disagreement Detection Report\n"]
    lines.append("## Summary\n")
    lines.append(f"- Market Reviewer decision: **{decisions.get('market', 'N/A')}**")
    lines.append(f"- Technology Reviewer decision: **{decisions.get('technology', 'N/A')}**")
    lines.append(f"- Business Reviewer decision: **{decisions.get('business', 'N/A')}**")
    lines.append(f"\n**Disagreements found: {len(disagreements)}**\n")

    if not disagreements:
        lines.append("✅ All reviewers agree. No committee discussion needed.\n")
        return "\n".join(lines)

    lines.append("## Disagreements Requiring Committee Discussion\n")
    for d in disagreements:
        lines.append(f"### {d['id']}: {d['issue']}")
        lines.append(f"**Severity:** {d['severity']}")
        lines.append(f"**Reviewer positions:**")
        for reviewer, pos in d["reviewer_positions"].items():
            lines.append(f"  - {reviewer.capitalize()}: {pos}")
        lines.append(f"**Why it matters:** {d['why_it_matters']}\n")

    return "\n".join(lines)


def main():
    COMMITTEE_DIR.mkdir(parents=True, exist_ok=True)

    texts: dict[str, str] = {}
    for name, path in REVIEW_FILES.items():
        if not path.exists():
            print(f"WARNING: {path} not found — skipping {name} reviewer", file=sys.stderr)
            texts[name] = ""
        else:
            texts[name] = path.read_text(encoding="utf-8")

    scores = {name: extract_scores(text) for name, text in texts.items()}
    decisions = {name: extract_decision(text) for name, text in texts.items() if text}
    disagreements = detect_disagreements(scores, decisions)

    # Write JSON
    output = {
        "decisions": decisions,
        "scores": scores,
        "disagreements": disagreements,
        "needs_committee_discussion": len(disagreements) > 0,
    }
    out_json = COMMITTEE_DIR / "disagreements.json"
    out_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print markdown to stdout for Claude Code
    md = format_markdown(decisions, scores, disagreements)
    print(md)

    # Exit code: 1 if disagreements exist (so Bash can check $?)
    sys.exit(1 if disagreements else 0)


if __name__ == "__main__":
    main()
