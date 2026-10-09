# Task 2 — NeoFirm AI Investment Committee

**GCS 9기 과제 #6 Task 2**  
**마감:** 2026-10-13 09:00  
**Entry point:** `/neofirm-invest [sector]`

---

## Architecture

```
Claude Code (slash command /neofirm-invest)
        ↓ orchestrates via Bash + Write tools
NotebookLM CLI (research)
        ↓
Investment Criteria (Claude Code writes directly)
        ↓
Market Reviewer     ┐
Technology Reviewer ├─ 3 independent Claude Code subagent calls
Business Reviewer   ┘  (each unaware of others' output)
        ↓
Disagreement Detection (Python helper: detect_disagreements.py)
        ↓
Committee Discussion (only if disagreements exist)
        ↓
Final Decision Maker (Claude Code writes investment_memo.md)
        ↓
PPTX Generation (Python helper: pptx_renderer.py)
```

**Claude Code = orchestrator**  
**Python = helper scripts only (PPTX, JSON parsing)**  
**No ANTHROPIC_API_KEY required**  
**No Anthropic Python SDK**

---

## How to Run

In VS Code with Claude Code extension, or in the Claude Code terminal:

```
/neofirm-invest 특허 출원·명세서 작성
```

Or for a different sector:

```
/neofirm-invest IT/소프트웨어
```

---

## File Structure

```
task2_neofirm/
├── README.md                          ← This file
├── agents/
│   └── reviewers.json                 ← Agent role definitions (--agents flag)
├── scripts/
│   ├── detect_disagreements.py        ← Score comparison → disagreements.json
│   └── pptx_renderer.py               ← slides_data.json → final.pptx
└── workspace/                         ← All generated artifacts
    ├── research/
    │   ├── research_report.md         ← NotebookLM answers (or fallback)
    │   └── evidence.json              ← Evidence items with IDs, confidence
    ├── criteria/
    │   └── investment_criteria.md     ← 10-criterion scoring rubric
    ├── reviews/
    │   ├── market_review.md           ← Market Reviewer output
    │   ├── technology_review.md       ← Technology Reviewer output
    │   └── business_review.md         ← Business Reviewer output
    ├── committee/
    │   ├── disagreements.json         ← Machine-readable disagreement data
    │   ├── disagreements.md           ← Human-readable disagreement summary
    │   ├── discussion.md              ← Committee discussion (if needed)
    │   └── resolution.md              ← Issue-by-issue resolution status
    ├── decision/
    │   └── investment_memo.md         ← Final INVEST/HOLD/PASS + rationale
    ├── presentation/
    │   ├── slides_data.json           ← Slide content (JSON)
    │   └── final_*.pptx               ← Final PPTX output
    └── logs/
        ├── execution_log.md           ← Per-step timestamps and status
        └── execution_summary.md       ← Overall run summary
```

---

## Key Design Decisions

### Why is Python NOT the orchestrator?

The assignment requires Claude Code itself to coordinate. Python scripts are helpers called via Bash — they handle PPTX rendering (deterministic formatting) and JSON parsing (score extraction). All AI reasoning, disagreement analysis, and committee discussion happen inside the Claude Code session.

### How are reviewers truly independent?

Each reviewer is a separate `claude --print --agent <name> --agents reviewers.json` subprocess call. A fresh subprocess has no context from the parent session or other reviewers.

### Why conditional committee discussion?

The `detect_disagreements.py` script identifies score gaps ≥ 2 or split decisions. If there are no disagreements, discussion is skipped. This prevents wasted computation and produces focused, evidence-based debate only where it matters.

---

## Prerequisites

- Claude Code installed and authenticated (`npx @anthropic-ai/claude-code --version`)
- NotebookLM CLI installed (`nlm --version`), ideally authenticated (`nlm login`)
- python-pptx installed (`pip install python-pptx`)
- NeoFirm notebook ID: `6b8429e2-cc08-466e-b785-ee6c0795112f`

NLM authentication can be refreshed with:
```
C:\Users\elice\AppData\Local\Python\pythoncore-3.14-64\Scripts\nlm.exe login
```

If NLM auth fails, the slash command falls back to Claude Code's own analysis using the existing `output/` reference files.

---

## Differences from Old Architecture

| | Old (scripts/run_neofirm.py) | New (task2_neofirm) |
|---|---|---|
| Orchestrator | Python script | Claude Code slash command |
| Agents | Market/Execution/Skeptic | Market/Technology/Business |
| Rounds | Fixed 3 rounds | Discussion only if disagreement |
| Decision | Synthesis | INVEST/HOLD/PASS investment memo |
| Python role | Central orchestrator | Helper only (PPTX, JSON) |
| API Key | Not needed (same) | Not needed |
