# NeoFirm AI Investment Committee

**Usage:** `/neofirm-invest [sector]`
**Example:** `/neofirm-invest 특허 출원·명세서 작성`

You are running the **NeoFirm AI Investment Committee** pipeline.
Your job is to orchestrate the full workflow and produce an INVEST/HOLD/PASS recommendation with supporting evidence.

The sector/topic to analyze is: **$ARGUMENTS**
If no argument was given, default to: **특허 출원·명세서 작성 (AI 법률 자동화)**

---

## RULES — READ FIRST

1. **Do NOT use ANTHROPIC_API_KEY** or the Anthropic Python SDK directly.
2. **Python is for helpers only** (PPTX rendering, JSON parsing). Python does NOT orchestrate AI agents.
3. **You are the orchestrator.** Use your Bash tool to call `nlm` and reviewer subagents. Use your Write/Edit tools to create files.
4. **3 independent reviewers** must NOT read each other's outputs before completing their own review. Run them as separate subprocess calls.
5. **Committee discussion only runs if disagreements are detected.** Do not debate topics where all reviewers agree.
6. **Never invent evidence.** If NotebookLM doesn't have the data, say so explicitly and label it as an assumption.
7. **Task 1.1 and Task 1.2 files must not be touched.** Only write inside `task2_neofirm/workspace/`.

---

## ENVIRONMENT SETUP

Run this first to confirm tools and initialize logging:

```bash
SECTOR="$ARGUMENTS"
SECTOR="${SECTOR:-특허 출원·명세서 작성}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WORKSPACE="task2_neofirm/workspace"
NLM="C:/Users/elice/AppData/Local/Python/pythoncore-3.14-64/Scripts/nlm.exe"
CLAUDE="C:/Program Files/nodejs/npx.cmd"
NOTEBOOK_ID="6b8429e2-cc08-466e-b785-ee6c0795112f"
REVIEWERS_JSON="task2_neofirm/agents/reviewers.json"

echo "=== NeoFirm Investment Committee ===" 
echo "Sector: $SECTOR"
echo "Timestamp: $TIMESTAMP"
echo "Workspace: $WORKSPACE"

# Check Claude Code
"$CLAUDE" --yes @anthropic-ai/claude-code --version 2>&1 | head -1

# Check NLM
"$NLM" --version 2>&1 | head -1

mkdir -p "$WORKSPACE/research" "$WORKSPACE/criteria" "$WORKSPACE/reviews" \
         "$WORKSPACE/committee" "$WORKSPACE/decision" "$WORKSPACE/presentation" \
         "$WORKSPACE/logs"

# Initialize execution log
cat > "$WORKSPACE/logs/execution_log.md" << EOF
# NeoFirm Investment Committee — Execution Log
Date: $(date)
Sector: $SECTOR
Claude Code Version: $("$CLAUDE" --yes @anthropic-ai/claude-code --version 2>&1 | head -1)
NLM Version: $("$NLM" --version 2>&1 | head -1)
Notebook ID: $NOTEBOOK_ID

## Steps
EOF
```

---

## STEP 1 — NOTEBOOKLM RESEARCH

Query NotebookLM to research NeoFirm's problem, market, and risks.
If NLM authentication fails (error code 16), fall back to your own analysis using the existing reference material in `output/` and `output/C_투자메모.md`.

```bash
NLM="C:/Users/elice/AppData/Local/Python/pythoncore-3.14-64/Scripts/nlm.exe"
NOTEBOOK_ID="6b8429e2-cc08-466e-b785-ee6c0795112f"
WORKSPACE="task2_neofirm/workspace"

echo "## STEP 1: NotebookLM Research" >> "$WORKSPACE/logs/execution_log.md"
echo "Started: $(date)" >> "$WORKSPACE/logs/execution_log.md"

# Run 8 research queries
for QUERY in \
  "What problem is NeoFirm solving and who is the target customer?" \
  "What evidence supports the existence and severity of this problem?" \
  "What is the total addressable market opportunity for NeoFirm?" \
  "What technical constraints or implementation risks exist?" \
  "What business model and monetization approach does NeoFirm use?" \
  "What are the main business risks and competitive threats?" \
  "What assumptions in NeoFirm's thesis are still unverified?" \
  "What additional customer validation is needed before investing?"; do
  echo "Query: $QUERY"
  RESULT=$("$NLM" notebook query --notebook-id "$NOTEBOOK_ID" "$QUERY" 2>&1)
  if echo "$RESULT" | grep -q "authentication may have expired"; then
    echo "NLM AUTH FAILED — will use fallback" >> "$WORKSPACE/logs/execution_log.md"
    echo "NLM_AUTH_FAILED"
    break
  fi
  echo "### $QUERY" >> "$WORKSPACE/research/research_report.md"
  echo "$RESULT" >> "$WORKSPACE/research/research_report.md"
  echo "" >> "$WORKSPACE/research/research_report.md"
done
```

**If NLM authentication fails**, read the existing reference files and write the research report yourself:
- Read `output/C_투자메모.md` (investment memo reference)
- Read `output/A_가치사슬.md` (value chain reference)
- Read `output/D_문제정의.md` (problem definition reference)
- Write a comprehensive `task2_neofirm/workspace/research/research_report.md` answering all 8 research questions above based on that material
- Note clearly: "Source: existing NeoFirm reference material (output/ directory)" 

After writing `research_report.md`, create `task2_neofirm/workspace/research/evidence.json` with at minimum 8 evidence items extracted from the research. Each item must follow:
```json
{
  "id": "E01",
  "statement": "Concrete factual claim",
  "source": "Source file or NLM notebook",
  "confidence": "high | medium | low",
  "category": "market | technical | business | customer | risk"
}
```
Only include verifiable claims. Label unverified assumptions with confidence "low" and add a note "(assumption)".

Log the result:
```
echo "Research report: DONE | Evidence JSON: DONE" >> task2_neofirm/workspace/logs/execution_log.md
```

---

## STEP 2 — INVESTMENT CRITERIA

Write `task2_neofirm/workspace/criteria/investment_criteria.md`.

Include exactly these 10 criteria with clear 1–5 scoring rubrics. The reviewers will use these same criteria:

| Criterion | 1 (Weak) | 3 (Moderate) | 5 (Strong) |
|---|---|---|---|
| problem_severity | Nice-to-have, low pain | Significant pain, some workarounds | Severe pain, no good alternatives |
| customer_evidence | No customer interviews | A few informal conversations | Validated by 5+ paying customers or LOIs |
| market_opportunity | <$50M TAM | $50M–$500M TAM | >$500M TAM with clear SAM path |
| differentiation | Feature parity with incumbents | Clear differentiators | Deep moat (IP, data, network effects) |
| technical_feasibility | Requires unsolved research | Hard but solvable with right team | Proven stack, team has built it before |
| execution_feasibility | Key hires not identified | Core team in place, gaps remain | Full team with domain expertise |
| business_model | Unclear path to revenue | Revenue model defined, unproven | Proven unit economics (paying customers) |
| scalability | Manual/linear scaling only | Some automation, moderate scaling | Near-zero marginal cost at scale |
| risk | Multiple existential risks | Manageable risks with mitigation plans | Well-understood risks with clear hedges |
| evidence_quality | Mostly assumptions | Mix of data and assumptions | Primarily data-backed with named sources |

Log: `echo "Investment criteria: DONE" >> task2_neofirm/workspace/logs/execution_log.md`

---

## STEP 3 — INDEPENDENT REVIEWER SUBAGENTS

Run 3 reviewer subagents **independently**. Each subprocess gets only:
- The research report
- The evidence JSON
- The investment criteria
- Its own role definition from `reviewers.json`

They do NOT get other reviewers' outputs.

```bash
CLAUDE="C:/Program Files/nodejs/npx.cmd"
REVIEWERS_JSON="task2_neofirm/agents/reviewers.json"
WORKSPACE="task2_neofirm/workspace"

echo "## STEP 3: Independent Reviews" >> "$WORKSPACE/logs/execution_log.md"

for REVIEWER in market_reviewer technology_reviewer business_reviewer; do
  echo "Running $REVIEWER..."
  START=$(date +%s)

  PROMPT="You are reviewing NeoFirm for the AI Investment Committee.

== RESEARCH REPORT ==
$(cat $WORKSPACE/research/research_report.md)

== EVIDENCE ==
$(cat $WORKSPACE/research/evidence.json)

== INVESTMENT CRITERIA ==
$(cat $WORKSPACE/criteria/investment_criteria.md)

Using the structure defined in your role, produce your independent review."

  OUTPUT=$(echo "$PROMPT" | "$CLAUDE" --yes @anthropic-ai/claude-code \
    --print \
    --output-format text \
    --no-session-persistence \
    --agents "$REVIEWERS_JSON" \
    --agent "$REVIEWER" \
    --disallowedTools "Bash,Edit,Write,Read,Glob,Grep,Agent,WebFetch,WebSearch,AskUserQuestion,TodoWrite,NotebookEdit" \
    2>/dev/null)

  END=$(date +%s)
  ELAPSED=$((END - START))

  # Map reviewer name to output file
  case "$REVIEWER" in
    market_reviewer)    OUTFILE="$WORKSPACE/reviews/market_review.md" ;;
    technology_reviewer) OUTFILE="$WORKSPACE/reviews/technology_review.md" ;;
    business_reviewer)  OUTFILE="$WORKSPACE/reviews/business_review.md" ;;
  esac

  echo "$OUTPUT" > "$OUTFILE"
  echo "$REVIEWER: DONE (${ELAPSED}s) -> $OUTFILE" >> "$WORKSPACE/logs/execution_log.md"
done
```

After this step, confirm all 3 files exist and are non-empty. If any reviewer subprocess fails (rc≠0 or empty output), write the review yourself while strictly following that reviewer's persona and output structure from `reviewers.json`.

---

## STEP 4 — DISAGREEMENT DETECTION

```bash
WORKSPACE="task2_neofirm/workspace"
echo "## STEP 4: Disagreement Detection" >> "$WORKSPACE/logs/execution_log.md"
python task2_neofirm/scripts/detect_disagreements.py 2>&1 | tee -a "$WORKSPACE/committee/disagreements.md"
EXIT_CODE=$?
echo "Disagreements detected: $([ $EXIT_CODE -eq 1 ] && echo YES || echo NO)" >> "$WORKSPACE/logs/execution_log.md"
```

Read `task2_neofirm/workspace/committee/disagreements.json` to understand:
- Which criteria have score gaps ≥ 2
- Whether reviewers reached different INVEST/HOLD/PASS decisions
- Severity ratings

---

## STEP 5 — COMMITTEE DISCUSSION (conditional)

**Only execute this step if `disagreements.json` has `"needs_committee_discussion": true`.**

For each disagreement in `disagreements.json`, run a focused committee discussion. You act as the moderator, then give each reviewer a voice to defend or revise their position based on the evidence.

Write the full discussion to `task2_neofirm/workspace/committee/discussion.md` with this structure:
```
## Committee Discussion

### Issue [ID]: [Issue title]
**Severity:** [HIGH/MEDIUM]
**Evidence referenced:** [E01, E03, ...]

#### Market Reviewer defends/challenges:
[position]

#### Technology Reviewer defends/challenges:
[position]

#### Business Reviewer evaluates:
[position]

#### Resolution: RESOLVED / PARTIALLY RESOLVED / UNRESOLVED
[Explanation of what was settled and what remains open]
```

Then write `task2_neofirm/workspace/committee/resolution.md` summarizing:
- Which issues are RESOLVED (and how)
- Which are UNRESOLVED (and why they couldn't be settled)
- Overall confidence impact (do unresolved issues lower the committee's confidence?)

Log:
```
echo "Committee discussion: DONE | Resolved: X | Unresolved: Y" >> task2_neofirm/workspace/logs/execution_log.md
```

If there are NO disagreements, write to `task2_neofirm/workspace/committee/disagreements.md`:
> All 3 reviewers reached consensus. No committee discussion required.

---

## STEP 6 — FINAL DECISION MAKER

Read ALL of:
- `task2_neofirm/workspace/research/research_report.md`
- `task2_neofirm/workspace/criteria/investment_criteria.md`
- `task2_neofirm/workspace/reviews/market_review.md`
- `task2_neofirm/workspace/reviews/technology_review.md`
- `task2_neofirm/workspace/reviews/business_review.md`
- `task2_neofirm/workspace/committee/disagreements.md`
- `task2_neofirm/workspace/committee/discussion.md` (if it exists)
- `task2_neofirm/workspace/committee/resolution.md` (if it exists)

Then act as the Decision Maker agent (persona defined in `task2_neofirm/agents/reviewers.json` under `decision_maker`) and write `task2_neofirm/workspace/decision/investment_memo.md` with:

- **Final decision: INVEST / HOLD / PASS** (pick one)
- Confidence: HIGH / MEDIUM / LOW
- Top 3 reasons
- Major risks
- Unverified assumptions
- Conditions that would change the decision
- Next 3 validation actions

Do NOT simply average scores. The decision must reflect the discussion outcomes and explicitly address unresolved disagreements.

Log: `echo "Final decision: [INVEST/HOLD/PASS] | Confidence: [X]" >> task2_neofirm/workspace/logs/execution_log.md`

---

## STEP 7 — PRESENTATION GENERATION

Create `task2_neofirm/workspace/presentation/slides_data.json` with this structure:

```json
{
  "title": "NeoFirm AI Investment Committee",
  "sector": "$ARGUMENTS",
  "decision": "INVEST|HOLD|PASS",
  "scores_by_reviewer": {
    "market": {"problem_severity": X, "customer_evidence": X, ...},
    "technology": {"technical_feasibility": X, ...},
    "business": {"business_model": X, ...}
  },
  "decisions_by_reviewer": {
    "market": "INVEST|HOLD|PASS",
    "technology": "INVEST|HOLD|PASS",
    "business": "INVEST|HOLD|PASS"
  },
  "slides": [
    {
      "slide_number": 1,
      "title": "NeoFirm — Problem & Target Customer",
      "key_points": ["...", "...", "..."],
      "badge": ""
    },
    {
      "slide_number": 2,
      "title": "Research Findings (NotebookLM)",
      "key_points": ["...", "..."],
      "badge": ""
    },
    {
      "slide_number": 3,
      "title": "Investment Criteria Scores",
      "key_points": ["Market: X/5 avg", "Technology: X/5 avg", "Business: X/5 avg"],
      "badge": ""
    },
    {
      "slide_number": 4,
      "title": "Where Reviewers Disagreed",
      "key_points": ["Issue D01: ...", "Issue D02: ..."],
      "badge": ""
    },
    {
      "slide_number": 5,
      "title": "Committee Discussion Outcome",
      "key_points": ["RESOLVED: ...", "UNRESOLVED: ..."],
      "badge": ""
    },
    {
      "slide_number": 6,
      "title": "Final Decision",
      "key_points": ["Decision: INVEST/HOLD/PASS", "Confidence: HIGH/MEDIUM/LOW", "Reason 1", "Reason 2", "Reason 3"],
      "badge": "INVEST"
    },
    {
      "slide_number": 7,
      "title": "Why",
      "key_points": ["...", "..."],
      "badge": ""
    },
    {
      "slide_number": 8,
      "title": "Next Validation Actions",
      "key_points": ["1. ...", "2. ...", "3. ..."],
      "badge": ""
    }
  ]
}
```

Then render the PPTX:

```bash
python task2_neofirm/scripts/pptx_renderer.py task2_neofirm/workspace/presentation/slides_data.json
```

Confirm the `.pptx` file was created under `task2_neofirm/workspace/presentation/`.

Log: `echo "PPTX: DONE -> task2_neofirm/workspace/presentation/final_*.pptx" >> task2_neofirm/workspace/logs/execution_log.md`

---

## STEP 8 — EXECUTION SUMMARY

Write `task2_neofirm/workspace/logs/execution_summary.md`:

```markdown
# NeoFirm Investment Committee — Execution Summary

**Date:** [date]
**Sector:** [sector]
**Final Decision:** INVEST / HOLD / PASS
**Confidence:** HIGH / MEDIUM / LOW

## Pipeline Status

| Step | Status | Notes |
|------|--------|-------|
| 1. NotebookLM Research | PASS/PARTIAL/FAIL | NLM or fallback? |
| 2. Investment Criteria | PASS | |
| 3. Market Review | PASS/FAIL | File: reviews/market_review.md |
| 4. Technology Review | PASS/FAIL | File: reviews/technology_review.md |
| 5. Business Review | PASS/FAIL | File: reviews/business_review.md |
| 6. Disagreement Detection | PASS | N disagreements found |
| 7. Committee Discussion | PASS/SKIP | N issues discussed |
| 8. Final Decision | PASS | |
| 9. PPTX Generation | PASS/FAIL | File: presentation/final_*.pptx |

## Evidence Files
- research/research_report.md ✅
- research/evidence.json ✅
- criteria/investment_criteria.md ✅
- reviews/market_review.md ✅
- reviews/technology_review.md ✅
- reviews/business_review.md ✅
- committee/disagreements.md ✅
- committee/discussion.md ✅/N/A
- committee/resolution.md ✅/N/A
- decision/investment_memo.md ✅
- presentation/slides_data.json ✅
- presentation/final_*.pptx ✅

## Overall: PASS / PARTIAL / FAIL
```

---

## FINAL CHECK

After completing all steps, print a summary table:

```
╔══════════════════════════════════════════════════════════════╗
║         NeoFirm AI Investment Committee — COMPLETE           ║
╠══════════════════════════════════════════════════════════════╣
║  Sector:         [sector]                                    ║
║  Decision:       INVEST / HOLD / PASS                        ║
║  Confidence:     HIGH / MEDIUM / LOW                         ║
║  Disagreements:  N found, M resolved, K unresolved           ║
║  PPTX:           task2_neofirm/workspace/presentation/*.pptx ║
╚══════════════════════════════════════════════════════════════╝
```

Then list every file created with its size.
