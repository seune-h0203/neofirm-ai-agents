#!/usr/bin/env python3
"""
run_neofirm.py — NeoFirm Task 2 orchestrator
Pipeline:
  NotebookLM CLI (research)
  → Claude Code CLI x3 agents, 3 rounds (debate)
  → Claude Code CLI (synthesis)
  → Claude Code CLI (slide JSON generation)
  → Claude Code CLI (quality review)
  → python-pptx (PPTX rendering)

Authentication: uses the locally authenticated Claude Code CLI session.
No ANTHROPIC_API_KEY required.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(exist_ok=True)

NOTEBOOK_ID = "6b8429e2-cc08-466e-b785-ee6c0795112f"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("neofirm")


# ---------------------------------------------------------------------------
# Claude Code CLI wrapper
# ---------------------------------------------------------------------------

def _find_claude_cmd() -> list[str]:
    """Return the command list to invoke Claude Code CLI non-interactively."""
    # Direct claude binary
    for name in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(name)
        if p:
            return [p]
    # npx — on Windows subprocess needs the .cmd extension
    for name in ("npx.cmd", "npx.exe", "npx"):
        p = shutil.which(name)
        if p:
            return [p, "--yes", "@anthropic-ai/claude-code"]
    # Fallback: hardcoded Node.js path (Windows)
    hardcoded = Path("C:/Program Files/nodejs/npx.cmd")
    if hardcoded.exists():
        return [str(hardcoded), "--yes", "@anthropic-ai/claude-code"]
    raise RuntimeError(
        "Cannot find 'claude' or 'npx' in PATH. "
        "Install Claude Code CLI: npm install -g @anthropic-ai/claude-code"
    )


CLAUDE_BASE = _find_claude_cmd()

_NO_TOOL_FLAGS = [
    "--disallowedTools",
    "Bash,Edit,Write,Read,Glob,Grep,Agent,WebFetch,WebSearch,"
    "AskUserQuestion,TodoWrite,NotebookEdit",
]


def claude(
    prompt: str,
    system_role: str = "",
    timeout: int = 180,
    label: str = "claude",
    run_dir: Path | None = None,
) -> str:
    """
    Invoke Claude Code CLI once, non-interactively, and return the text response.
    Uses the locally-authenticated Claude session — no ANTHROPIC_API_KEY required.
    """
    # Prompt is passed via stdin to avoid --disallowedTools consuming positional args
    cmd = CLAUDE_BASE + [
        "--print",
        "--output-format", "text",
        "--no-session-persistence",
    ] + _NO_TOOL_FLAGS

    if system_role:
        cmd += ["--append-system-prompt", system_role]

    log.info("[%s] Invoking Claude Code CLI…", label)
    t0 = time.time()

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(BASE_DIR),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"[{label}] Claude CLI timed out after {timeout}s")

    elapsed = time.time() - t0
    log.info("[%s] done in %.1fs (rc=%d)", label, elapsed, result.returncode)

    if result.returncode != 0:
        stderr_snippet = result.stderr.strip()[:400]
        raise RuntimeError(
            f"[{label}] Claude CLI exited {result.returncode}:\n{stderr_snippet}"
        )

    text = result.stdout.strip()
    if not text:
        raise RuntimeError(f"[{label}] Claude CLI returned empty output")

    # Save evidence
    if run_dir:
        _save_evidence(run_dir, label, prompt, system_role, text, elapsed)

    return text


def _save_evidence(
    run_dir: Path,
    label: str,
    prompt: str,
    system_role: str,
    response: str,
    elapsed: float,
) -> None:
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{ts}_{label.replace(' ', '_')}.json"
    record = {
        "label": label,
        "timestamp": ts,
        "claude_cmd": CLAUDE_BASE[0],
        "elapsed_s": round(elapsed, 2),
        "prompt_length": len(prompt),
        "system_role_length": len(system_role),
        "response_length": len(response),
        "response_preview": response[:300],
    }
    (evidence_dir / fname).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# NotebookLM CLI wrapper
# ---------------------------------------------------------------------------

def _find_nlm() -> str | None:
    found = shutil.which("nlm")
    if found:
        return found
    venv_bin = Path(sys.executable).parent
    if platform.system() == "Windows":
        for name in ("nlm.exe", "nlm.cmd"):
            p = venv_bin / "Scripts" / name
            if p.exists():
                return str(p)
    else:
        p = venv_bin / "nlm"
        if p.exists():
            return str(p)
    local = Path.home() / ".local" / "bin"
    for name in (("nlm.exe", "nlm.cmd", "nlm") if platform.system() == "Windows" else ("nlm",)):
        p = local / name
        if p.exists():
            return str(p)
    return None


NLM = _find_nlm()
log.info("NLM executable: %r", NLM)


def nlm_query(question: str, label: str = "nlm") -> str:
    """Query NotebookLM CLI. Falls back to Claude CLI if NLM is unavailable."""
    if not NLM:
        log.warning("[%s] nlm not found — falling back to Claude CLI for research", label)
        return claude(
            f"Answer the following research question with detailed, structured analysis:\n\n{question}",
            system_role="You are a professional research analyst. Provide thorough, evidence-based analysis.",
            label=f"{label}_fallback",
            timeout=120,
        )

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"

    cmd = [NLM, "notebook", "query", NOTEBOOK_ID, question]
    try:
        result = subprocess.run(
            cmd, capture_output=True, env=env,
            timeout=180, text=True, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"[{label}] nlm timed out after 180s")

    if result.returncode != 0:
        msg = result.stdout.strip() or result.stderr.strip()
        raise RuntimeError(f"[{label}] nlm failed rc={result.returncode}: {msg[:300]}")

    answer = result.stdout.strip()
    for sep in ("\nSources:", "\n\nSources:", "\nConversation ID:"):
        idx = answer.find(sep)
        if idx != -1:
            answer = answer[:idx].strip()
            break
    if not answer:
        raise RuntimeError(f"[{label}] nlm returned empty response")
    return answer


# ---------------------------------------------------------------------------
# Phase 1: Research
# ---------------------------------------------------------------------------

RESEARCH_QUESTIONS = {
    "value_chain": (
        "전문서비스 영역: {sector}\n\n"
        "NeoFirm 과제 A (기존 가치사슬 해부)를 작성해줘. "
        "고객은 누구에게 어떤 결과를 사는지, "
        "현재 업무 단계와 담당자·소요시간·오류율, "
        "공급자의 매출 구조, 고객이 싫어하는 병목을 포함해줘."
    ),
    "task_distribution": (
        "전문서비스 영역: {sector}\n\n"
        "NeoFirm 과제 B (AI-전문가 작업 배분표)를 작성해줘. "
        "자동화/보조/전문가전담/금지 4가지 구분으로 표를 만들어줘."
    ),
    "investment_memo": (
        "전문서비스 영역: {sector}\n\n"
        "NeoFirm 과제 C (1페이지 투자메모)를 작성해줘. "
        "시장 규모, 표준화할 업무, 가격 구조, 전문가 개입률, "
        "책임·보험·규제, 독점 데이터, SaaS vs 직접 서비스를 포함해줘."
    ),
    "problem_definition": (
        "전문서비스 영역: {sector}\n\n"
        "NeoFirm 문제정의문과 타깃 고객 프로필, 핵심 가치제안, KPI 3가지를 작성해줘."
    ),
}


def run_research(run_dir: Path, sector: str) -> dict[str, str]:
    log.info("=== Phase 1: Research (NotebookLM) ===")
    research: dict[str, str] = {}

    for key, q_template in RESEARCH_QUESTIONS.items():
        question = q_template.format(sector=sector)
        log.info("  Querying: %s", key)
        try:
            answer = nlm_query(question, label=f"nlm_{key}")
        except Exception as exc:
            log.error("  NLM query %s failed: %s — using Claude fallback", key, exc)
            answer = claude(
                question,
                system_role="You are a professional analyst specializing in Korean professional services.",
                label=f"research_{key}",
                run_dir=run_dir,
                timeout=120,
            )
        research[key] = answer

    # Save research.md
    research_md = run_dir / "research.md"
    lines = [f"# NeoFirm Research — {sector}\n\n**Generated:** {datetime.now()}\n\n"]
    for key, text in research.items():
        lines.append(f"## {key.replace('_', ' ').title()}\n\n{text}\n\n---\n\n")
    research_md.write_text("".join(lines), encoding="utf-8")
    log.info("  Saved: %s", research_md)
    return research


# ---------------------------------------------------------------------------
# Phase 2: Agent Debate
# ---------------------------------------------------------------------------

AGENT_ROLES = {
    "market": (
        "You are the Market Agent. Your role is to analyze NeoFirm from the "
        "market and customer perspective. Focus on: customer pain points, "
        "market size, customer willingness to pay, competitive landscape, and "
        "go-to-market strategy. Respond in Korean. Be specific and evidence-based."
    ),
    "execution": (
        "You are the Execution Agent. Your role is to analyze NeoFirm from the "
        "technical and operational feasibility perspective. Focus on: technology "
        "stack, AI capabilities, process automation, talent requirements, "
        "scalability, and operational risks. Respond in Korean. Be specific."
    ),
    "skeptic": (
        "You are the Skeptic Agent. Your role is to challenge assumptions and "
        "identify risks in the NeoFirm proposal. Focus on: unvalidated assumptions, "
        "regulatory/legal risks, quality risks, competitive threats, failure modes. "
        "Respond in Korean. Be constructively critical and specific."
    ),
}


def _debate_round1_agent(
    agent: str,
    research: dict[str, str],
    sector: str,
    run_dir: Path,
) -> tuple[str, str]:
    research_summary = "\n\n".join(
        f"### {k.replace('_', ' ').title()}\n{v[:600]}" for k, v in research.items()
    )
    prompt = textwrap.dedent(f"""
        다음은 '{sector}' 전문서비스 영역에 대한 NeoFirm 과제 리서치 결과입니다:

        {research_summary}

        위 리서치를 바탕으로, 당신의 역할 관점에서 NeoFirm 사업 제안에 대한
        독립적인 입장(Round 1 포지션)을 제시하세요.

        다음을 포함해 주세요:
        1. 핵심 주장 3가지 (구체적 근거 포함)
        2. 가장 중요한 기회/우려 사항
        3. 최종 판단: 이 사업의 실현 가능성 평가 (높음/중간/낮음 + 이유)

        한국어로 작성. 500자 이상.
    """).strip()

    response = claude(
        prompt,
        system_role=AGENT_ROLES[agent],
        label=f"round1_{agent}",
        run_dir=run_dir,
        timeout=180,
    )
    return agent, response


def run_debate_round1(
    run_dir: Path,
    research: dict[str, str],
    sector: str,
) -> dict[str, str]:
    log.info("=== Phase 2: Debate Round 1 (independent proposals) ===")
    positions: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_debate_round1_agent, agent, research, sector, run_dir): agent
            for agent in AGENT_ROLES
        }
        for fut in as_completed(futures):
            agent, response = fut.result()
            positions[agent] = response
            log.info("  [Round 1] %s done (%d chars)", agent, len(response))

    return positions


def _debate_round2_agent(
    agent: str,
    round1: dict[str, str],
    sector: str,
    run_dir: Path,
) -> tuple[str, str]:
    others_text = "\n\n".join(
        f"**{other.upper()} Agent (Round 1):**\n{text[:800]}"
        for other, text in round1.items()
        if other != agent
    )
    my_r1 = round1[agent][:600]

    prompt = textwrap.dedent(f"""
        영역: {sector}

        **나의 Round 1 포지션:**
        {my_r1}

        **다른 에이전트들의 Round 1 포지션:**
        {others_text}

        Round 2: 위 포지션들을 읽고 반박/도전하세요.

        다음을 포함해 주세요:
        1. 다른 에이전트의 주장 중 동의하기 어려운 점 2가지 (왜 틀렸는지 구체적 근거)
        2. 내 Round 1 포지션을 강화하는 추가 논거
        3. 가장 핵심적인 논쟁 포인트 1가지 제시

        한국어로 작성. 400자 이상.
    """).strip()

    response = claude(
        prompt,
        system_role=AGENT_ROLES[agent],
        label=f"round2_{agent}",
        run_dir=run_dir,
        timeout=180,
    )
    return agent, response


def run_debate_round2(
    run_dir: Path,
    round1: dict[str, str],
    sector: str,
) -> dict[str, str]:
    log.info("=== Phase 2: Debate Round 2 (rebuttals) ===")
    rebuttals: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_debate_round2_agent, agent, round1, sector, run_dir): agent
            for agent in AGENT_ROLES
        }
        for fut in as_completed(futures):
            agent, response = fut.result()
            rebuttals[agent] = response
            log.info("  [Round 2] %s done (%d chars)", agent, len(response))

    return rebuttals


def _debate_round3_agent(
    agent: str,
    round1: dict[str, str],
    round2: dict[str, str],
    sector: str,
    run_dir: Path,
) -> tuple[str, str]:
    others_r2 = "\n\n".join(
        f"**{other.upper()} Agent (Round 2 rebuttal):**\n{text[:600]}"
        for other, text in round2.items()
        if other != agent
    )
    my_r1 = round1[agent][:500]
    my_r2 = round2[agent][:500]

    prompt = textwrap.dedent(f"""
        영역: {sector}

        **나의 Round 1:**
        {my_r1}

        **나의 Round 2 반박:**
        {my_r2}

        **다른 에이전트들의 Round 2 반박:**
        {others_r2}

        Round 3: 모든 반박을 고려하여 최종 입장을 정리하세요.

        반드시 명시하세요:
        - [유지] / [수정] / [철회] 중 하나를 선택하고 이유 설명
        - 수정 또는 철회 시: 어떻게 바뀌었는지 구체적으로
        - 유지 시: 반박에도 불구하고 왜 옳은지 새 근거 제시
        - 이 사업의 핵심 성공 조건 1가지

        한국어로 작성. 400자 이상.
    """).strip()

    response = claude(
        prompt,
        system_role=AGENT_ROLES[agent],
        label=f"round3_{agent}",
        run_dir=run_dir,
        timeout=180,
    )
    return agent, response


def run_debate_round3(
    run_dir: Path,
    round1: dict[str, str],
    round2: dict[str, str],
    sector: str,
) -> dict[str, str]:
    log.info("=== Phase 2: Debate Round 3 (revisions) ===")
    revisions: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_debate_round3_agent, agent, round1, round2, sector, run_dir): agent
            for agent in AGENT_ROLES
        }
        for fut in as_completed(futures):
            agent, response = fut.result()
            revisions[agent] = response
            log.info("  [Round 3] %s done (%d chars)", agent, len(response))

    return revisions


def save_debate_log(
    run_dir: Path,
    sector: str,
    round1: dict[str, str],
    round2: dict[str, str],
    round3: dict[str, str],
) -> Path:
    lines: list[str] = [
        f"# NeoFirm AI Agent Debate Log\n\n",
        f"**영역:** {sector}  \n",
        f"**생성:** {datetime.now()}\n\n",
        "---\n\n",
    ]

    for rnum, rdata in [("Round 1 — 독립 포지션", round1),
                        ("Round 2 — 반박", round2),
                        ("Round 3 — 최종 입장", round3)]:
        lines.append(f"## {rnum}\n\n")
        for agent, text in rdata.items():
            lines.append(f"### {agent.upper()} Agent\n\n{text}\n\n")
        lines.append("---\n\n")

    debate_md = run_dir / "debate.md"
    debate_md.write_text("".join(lines), encoding="utf-8")
    log.info("Saved debate log: %s", debate_md)
    return debate_md


# ---------------------------------------------------------------------------
# Phase 3: Final Synthesis
# ---------------------------------------------------------------------------

def run_synthesis(
    run_dir: Path,
    sector: str,
    round1: dict[str, str],
    round2: dict[str, str],
    round3: dict[str, str],
    research: dict[str, str],
) -> str:
    log.info("=== Phase 3: Final Synthesis ===")

    debate_summary = "\n\n".join(
        f"**{agent.upper()} Agent 최종 입장:**\n{text[:700]}"
        for agent, text in round3.items()
    )
    research_summary = "\n\n".join(
        f"**{k}:**\n{v[:400]}" for k, v in research.items()
    )

    prompt = textwrap.dedent(f"""
        영역: {sector}

        ## 에이전트 토론 최종 입장 요약:
        {debate_summary}

        ## 리서치 요약:
        {research_summary}

        위 내용을 바탕으로 NeoFirm 과제 최종 종합 결론을 작성하세요.

        반드시 포함:
        1. 각 에이전트의 핵심 합의점 (시장/실행/회의론자가 동의한 것)
        2. 주요 미해결 갈등 포인트
        3. 최종 사업 타당성 결론 (근거 포함)
        4. NeoFirm이 성공하기 위한 핵심 조건 3가지
        5. 첫 번째 실행 단계 권고사항

        한국어로, 체계적이고 구체적으로 800자 이상 작성.
    """).strip()

    synthesis = claude(
        prompt,
        system_role=(
            "You are the Final Synthesis Agent. Your role is to objectively integrate "
            "all debate positions into a coherent final conclusion. Be balanced, "
            "evidence-based, and constructive. Respond in Korean."
        ),
        label="synthesis",
        run_dir=run_dir,
        timeout=180,
    )

    (run_dir / "synthesis.md").write_text(
        f"# NeoFirm Final Synthesis\n\n**영역:** {sector}\n\n{synthesis}",
        encoding="utf-8",
    )
    return synthesis


# ---------------------------------------------------------------------------
# Phase 4: Slide Generation
# ---------------------------------------------------------------------------

SLIDE_JSON_SCHEMA = {
    "type": "object",
    "required": ["title", "sector", "slides"],
    "properties": {
        "title": {"type": "string"},
        "sector": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slide_number", "title", "key_points"],
                "properties": {
                    "slide_number": {"type": "integer"},
                    "title": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "body": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        },
        "debate_summary": {"type": "string"},
        "conclusion": {"type": "string"},
    },
}


def run_slide_generation(
    run_dir: Path,
    sector: str,
    synthesis: str,
    research: dict[str, str],
    round3: dict[str, str],
) -> dict:
    log.info("=== Phase 4: Slide Generation ===")

    debate_key_points = "\n".join(
        f"- {agent.upper()}: {text[:200]}" for agent, text in round3.items()
    )

    prompt = textwrap.dedent(f"""
        영역: {sector}

        ## 최종 종합 결론:
        {synthesis[:800]}

        ## 에이전트 토론 핵심:
        {debate_key_points}

        아래 JSON 스키마에 맞는 발표 슬라이드 콘텐츠를 생성하세요.
        반드시 슬라이드 8개 이상 포함하세요:
        1. 표지 (title, sector)
        2. 문제 정의
        3. 시장 분석
        4. 가치사슬 분석
        5. NeoFirm 솔루션
        6. AI 에이전트 토론 요약 (시장/실행/회의론자 포지션)
        7. 최종 결론
        8. 실행 로드맵

        JSON만 반환하세요 (마크다운 코드블록 없이).
        스키마: {json.dumps(SLIDE_JSON_SCHEMA, ensure_ascii=False)}
    """).strip()

    raw = claude(
        prompt,
        system_role=(
            "You are a professional presentation designer. "
            "Generate ONLY valid JSON matching the schema provided. "
            "Do not include markdown fences or any text outside the JSON object."
        ),
        label="slide_generation",
        run_dir=run_dir,
        timeout=180,
    )

    # Clean up any markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        slides_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Slide JSON parse error: %s — saving raw", exc)
        (run_dir / "slides_raw.txt").write_text(raw, encoding="utf-8")
        raise RuntimeError(f"Slide generation returned invalid JSON: {exc}")

    (run_dir / "slides.json").write_text(
        json.dumps(slides_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return slides_data


# ---------------------------------------------------------------------------
# Phase 5: Quality Review
# ---------------------------------------------------------------------------

def run_quality_review(
    run_dir: Path,
    sector: str,
    slides_data: dict,
    debate_present: bool = True,
) -> dict:
    log.info("=== Phase 5: Quality Review ===")

    slides_preview = json.dumps(slides_data, ensure_ascii=False)[:1500]

    prompt = textwrap.dedent(f"""
        영역: {sector}

        다음 NeoFirm 발표 슬라이드 콘텐츠를 검토하세요:
        {slides_preview}

        아래 기준으로 검토 후 JSON으로 결과를 반환하세요:
        1. required_content_present: 문제정의/시장분석/솔루션/결론 포함 여부 (true/false)
        2. claims_grounded: 주장이 리서치 근거 기반인지 (true/false)
        3. debate_reflected: 에이전트 토론 결과가 반영되었는지 (true/false)
        4. slide_count_ok: 슬라이드 8개 이상인지 (true/false)
        5. logical_consistency: 슬라이드 흐름이 논리적인지 (true/false)
        6. overall_pass: 위 5가지 모두 true면 true
        7. issues: 문제점 목록 (문자열 배열, 없으면 빈 배열)
        8. suggestions: 개선 제안 목록 (문자열 배열)

        JSON만 반환하세요.
    """).strip()

    raw = claude(
        prompt,
        system_role=(
            "You are an independent quality reviewer for NeoFirm presentations. "
            "Be strict and objective. Return ONLY valid JSON."
        ),
        label="quality_review",
        run_dir=run_dir,
        timeout=120,
    )

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        review = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Review JSON parse failed — treating as fail")
        review = {
            "overall_pass": False,
            "issues": ["Review JSON parse failed"],
            "suggestions": [],
        }

    (run_dir / "review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return review


def run_slide_revision(
    run_dir: Path,
    sector: str,
    slides_data: dict,
    review: dict,
    synthesis: str,
    research: dict[str, str],
    round3: dict[str, str],
) -> dict:
    log.info("=== Phase 4b: Slide Revision ===")

    issues = "\n".join(f"- {i}" for i in review.get("issues", []))
    suggestions = "\n".join(f"- {s}" for s in review.get("suggestions", []))
    current_json = json.dumps(slides_data, ensure_ascii=False)[:1200]

    prompt = textwrap.dedent(f"""
        영역: {sector}

        현재 슬라이드 (수정 필요):
        {current_json}

        검토자 지적 사항:
        {issues}

        개선 제안:
        {suggestions}

        최종 종합 결론 (참고):
        {synthesis[:600]}

        위 문제점을 수정한 새 슬라이드 JSON을 반환하세요.
        JSON만 반환 (마크다운 없이).
        스키마: {json.dumps(SLIDE_JSON_SCHEMA, ensure_ascii=False)}
    """).strip()

    raw = claude(
        prompt,
        system_role=(
            "You are a professional presentation designer fixing review feedback. "
            "Return ONLY valid JSON."
        ),
        label="slide_revision",
        run_dir=run_dir,
        timeout=180,
    )

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        revised = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Revised slide JSON parse error: %s — keeping original", exc)
        return slides_data

    return revised


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(sector: str, max_review_attempts: int = 3) -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info("NeoFirm Pipeline Start | sector=%r | run_id=%s", sector, run_id)
    log.info("=" * 60)

    # Phase 1: Research
    research = run_research(run_dir, sector)

    # Phase 2: Debate (3 rounds)
    round1 = run_debate_round1(run_dir, research, sector)
    round2 = run_debate_round2(run_dir, round1, sector)
    round3 = run_debate_round3(run_dir, round1, round2, sector)
    save_debate_log(run_dir, sector, round1, round2, round3)

    # Phase 3: Synthesis
    synthesis = run_synthesis(run_dir, sector, round1, round2, round3, research)

    # Phase 4+5: Slide generation with review loop
    slides_data = run_slide_generation(run_dir, sector, synthesis, research, round3)

    for attempt in range(1, max_review_attempts + 1):
        review = run_quality_review(run_dir, sector, slides_data)
        log.info("[Review attempt %d/%d] pass=%s", attempt, max_review_attempts, review.get("overall_pass"))

        if review.get("overall_pass"):
            log.info("Quality review PASSED")
            break

        if attempt < max_review_attempts:
            log.warning("Review FAILED — revising slides (attempt %d)", attempt)
            slides_data = run_slide_revision(
                run_dir, sector, slides_data, review, synthesis, research, round3
            )
        else:
            log.warning("Max review attempts reached — proceeding with current slides")

    # PPTX rendering
    try:
        from scripts.render_neofirm import render_pptx
    except ImportError:
        sys.path.insert(0, str(BASE_DIR / "scripts"))
        from render_neofirm import render_pptx

    pptx_path = render_pptx(run_dir, sector, slides_data)
    log.info("PPTX saved: %s", pptx_path)

    # Final manifest
    manifest = {
        "run_id": run_id,
        "sector": sector,
        "timestamp": datetime.now().isoformat(),
        "phases": {
            "research": "completed",
            "debate_round1": "completed",
            "debate_round2": "completed",
            "debate_round3": "completed",
            "synthesis": "completed",
            "slide_generation": "completed",
            "quality_review": review.get("overall_pass", False),
            "pptx_rendering": str(pptx_path.name),
        },
        "claude_cmd": CLAUDE_BASE[0],
        "nlm_path": NLM,
        "pptx_path": str(pptx_path),
        "review_pass": review.get("overall_pass", False),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info("=" * 60)
    log.info("Pipeline complete | PPTX: %s", pptx_path)
    log.info("=" * 60)
    return pptx_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="NeoFirm Task 2 — Claude Code CLI pipeline")
    p.add_argument("sector", help="전문서비스 영역 (예: IT/소프트웨어)")
    p.add_argument("--max-reviews", type=int, default=3, help="Quality review max retries")
    args = p.parse_args()

    try:
        pptx_path = run_pipeline(args.sector, max_review_attempts=args.max_reviews)
        print(f"\n[OK] PPTX: {pptx_path}")
        sys.exit(0)
    except Exception as exc:
        log.error("Pipeline failed: %s", exc, exc_info=True)
        print(f"\n[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
