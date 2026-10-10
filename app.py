"""
NeoFirm 과제 자동 생성 웹 서버
실행: python -m uvicorn app:app --reload --port 8000
"""
import asyncio
import json
import logging
import os
import platform
import shutil as _shutil
import subprocess
import sys
import textwrap
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"
LOGS_DIR = BASE_DIR / "logs"
WORKSPACE_DIR = BASE_DIR / "task2_neofirm" / "workspace"
NOTEBOOK_ID = "65c4ca8f-4c96-497c-b366-981567849412"

OUTPUT_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ── Error log setup ────────────────────────────────────────
_err_log = logging.getLogger("neofirm.generation")
_err_log.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOGS_DIR / "generation_error.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_err_log.addHandler(_fh)


def _find_nlm() -> str | None:
    """nlm 실행파일을 탐색한다. 못 찾으면 None 반환."""
    _is_win = platform.system() == "Windows"
    # 1. PATH 탐색 (크로스플랫폼)
    found = _shutil.which("nlm")
    if found:
        return found
    # 2. venv bin 디렉토리
    venv_bin = Path(sys.executable).parent
    candidates = (
        [venv_bin / "Scripts" / "nlm.exe", venv_bin / "Scripts" / "nlm.cmd"]
        if _is_win else [venv_bin / "nlm"]
    )
    for p in candidates:
        if p.exists():
            return str(p)
    # 3. 사용자 홈/.local/bin
    local_bin = Path.home() / ".local" / "bin"
    names = ("nlm.exe", "nlm.cmd", "nlm") if _is_win else ("nlm",)
    for name in names:
        p = local_bin / name
        if p.exists():
            return str(p)
    return None


NLM = _find_nlm()
_err_log.info(f"Server start — NLM executable: {NLM!r}  Python: {sys.executable}")


def _build_env() -> dict:
    """subprocess용 환경변수."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    # Windows에서만 Scripts 디렉토리를 PATH 앞에 추가
    if platform.system() == "Windows":
        scripts_dir = str(Path(sys.executable).parent / "Scripts")
        env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")
    return env


_executor = ThreadPoolExecutor(max_workers=4)


def _claude_fallback(question: str) -> str:
    """NLM 없을 때 Gemini로 시도 (503 재시도 포함)."""
    import httpx, time

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={gemini_key}",
                    headers={"content-type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": question}]}],
                        "generationConfig": {"maxOutputTokens": 1024},
                    },
                    timeout=60,
                )
                if resp.status_code == 200:
                    parts = resp.json()["candidates"][0]["content"]["parts"]
                    text = next((p["text"] for p in parts if "text" in p), "")
                    if text:
                        return text.strip()
                    _err_log.warning(f"Gemini 빈 응답 (시도 {attempt+1}/3)")
                elif resp.status_code == 503:
                    _err_log.warning(f"Gemini 503 (시도 {attempt+1}/3), {5*(attempt+1)}초 후 재시도")
                    time.sleep(5 * (attempt + 1))
                else:
                    _err_log.warning(f"Gemini {resp.status_code}: {resp.text[:200]}")
                    break
            except Exception as e:
                _err_log.warning(f"Gemini 호출 실패 (시도 {attempt+1}/3): {e}")
                time.sleep(3)

    raise RuntimeError("Gemini API 응답 실패 — 잠시 후 다시 시도해주세요")


def _run_nlm_sync(question: str) -> str:
    """
    Synchronous nlm call — runs in a thread so Windows SelectorEventLoop works.
    Falls back to Claude API if nlm is not available.
    Raises RuntimeError on failure.
    """
    nlm_path = NLM
    if not nlm_path:
        _err_log.warning("nlm not found — falling back to Claude API")
        return _claude_fallback(question)

    cmd = [nlm_path, "notebook", "query", NOTEBOOK_ID, question]
    env = _build_env()

    _err_log.debug(f"Running: {' '.join(cmd[:4])} <question>")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            env=env,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        _err_log.error("nlm timeout after 180s — Gemini fallback 시도")
        return _claude_fallback(question)

    stdout_text = result.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stderr_text = result.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()

    _err_log.debug(f"returncode={result.returncode}  stderr={stderr_text[:200]}")
    _err_log.debug(f"stdout (first 300): {stdout_text[:300]}")

    if result.returncode != 0:
        msg = stdout_text.strip() or stderr_text or f"nlm exited with code {result.returncode}"
        _err_log.error(f"nlm failed rc={result.returncode}: {msg[:300]}")
        _err_log.warning("nlm 실패 — Gemini fallback 시도")
        return _claude_fallback(question)

    answer = stdout_text.strip()
    for sep in ("\nSources:", "\n\nSources:", "\nConversation ID:", "\n\nConversation ID:"):
        idx = answer.find(sep)
        if idx != -1:
            answer = answer[:idx].strip()
            break

    if not answer:
        _err_log.warning("nlm 빈 응답 — Gemini fallback 시도")
        return _claude_fallback(question)

    return answer


async def run_nlm_query(question: str) -> str:
    """Async wrapper — delegates to thread pool to avoid Windows SelectorEventLoop limitation."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_nlm_sync, question)


QUERIES = {
    "A": {
        "title": "과제 A: 기존 가치사슬 해부 분석서",
        "step": "가치사슬",
        "question": (
            "전문서비스 영역: {sector}\n\n"
            "위 영역을 기준으로 NeoFirm 과제 A (기존 가치사슬 해부)를 작성해줘. "
            "반드시 아래 4가지 항목을 각각 구체적으로 답해줘:\n"
            "1. 고객은 누구에게 어떤 결과를 사는가?\n"
            "2. 현재 업무 단계와 각 단계별 담당자·소요시간·오류율은?\n"
            "3. 공급자의 매출이 시간·인원과 어떻게 연결되는가?\n"
            "4. 고객이 가장 싫어하는 대기, 재작업, 불확실성은 어디에서 생기는가?\n"
            "한국어로, 표나 bullet 형식으로 정리해줘."
        ),
    },
    "B": {
        "title": "과제 B: AI-전문가 작업 배분표",
        "step": "작업배분",
        "question": (
            "전문서비스 영역: {sector}\n\n"
            "위 영역을 기준으로 NeoFirm 과제 B (AI-전문가 작업 배분표)를 작성해줘. "
            "아래 4가지 구분으로 표를 만들어줘:\n"
            "- 자동화: 규칙이 명확하고 검증 가능한 반복작업\n"
            "- 보조(AI초안+전문가검증): AI가 초안을 내되 전문가가 쉽게 검증 가능한 작업\n"
            "- 전문가 전담: 모호성·이해상충·고위험 판단\n"
            "- 금지: 책임주체 불명확하거나 검증 불가능한 작업\n"
            "각 구분마다 구체적인 업무 예시를 3개 이상 포함해줘. 한국어 표 형식."
        ),
    },
    "C": {
        "title": "과제 C: 1페이지 투자메모",
        "step": "투자메모",
        "question": (
            "전문서비스 영역: {sector}\n\n"
            "위 영역을 기준으로 NeoFirm 과제 C (1페이지 투자메모)를 작성해줘. "
            "반드시 아래 7개 항목을 모두 포함해줘:\n"
            "1. 시장 규모 및 고객의 현재 지출 (한국 시장 기준 추정)\n"
            "2. 첫 번째로 표준화할 좁은 업무 (구체적인 서비스 단위)\n"
            "3. 결과 단위와 가격 구조 (건당 고정가 또는 성과가 예시)\n"
            "4. 전문가 개입률 목표와 품질 지표\n"
            "5. 책임·보험·규제 구조 (오류 시 책임 소재, 관련 법령)\n"
            "6. 100건 수행 후 쌓이는 독점 데이터 (어떤 데이터가 해자가 되는가)\n"
            "7. SaaS 판매보다 직접 서비스를 선택해야 하는 이유\n"
            "한국어로, 각 항목을 명확히 구분해서 작성해줘."
        ),
    },
    "D": {
        "title": "문제정의문",
        "step": "문제정의",
        "question": (
            "전문서비스 영역: {sector}\n\n"
            "위 영역을 기준으로 NeoFirm 문제정의문을 작성해줘. "
            "아래 템플릿을 채워서 완성된 문제정의문을 만들어줘:\n\n"
            "[고객]은 [전문서비스 결과]를 얻기 위해 [시간·비용·불확실성]을 감수하고 있다. "
            "기존 공급자는 [시간당 과금·수작업·파편화] 때문에 개선할 유인이 약하다. "
            "우리는 [AI 정상경로 처리]와 [전문가 예외판단]을 결합해 [측정 가능한 결과]를 "
            "[고정가·성과가]로 제공하고, [업무 피드백]을 축적해 매 건 더 빠르고 정확해지는 "
            "서비스를 만든다.\n\n"
            "추가로 다음도 작성해줘:\n"
            "- 타깃 고객 프로필 (1-2줄)\n"
            "- 핵심 가치제안 (1-2줄)\n"
            "- 첫 번째 KPI 3가지"
        ),
    },
}

app = FastAPI(title="NeoFirm Generator")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/debug")
async def debug_info():
    """개발용: nlm 탐색 결과 및 환경 확인."""
    return {
        "nlm_path": NLM,
        "nlm_which": _shutil.which("nlm"),
        "python_exe": sys.executable,
        "scripts_dir": str(Path(sys.executable).parent / "Scripts"),
        "scripts_nlm_exists": (Path(sys.executable).parent / "Scripts" / "nlm.exe").exists(),
        "cwd": str(Path.cwd()),
    }


class GenerateRequest(BaseModel):
    sector: str


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    sector = req.sector.strip()
    if not sector:
        raise HTTPException(400, "전문서비스 영역을 입력해주세요")

    results: dict = {}

    async def stream():
        # Clear previous workspace data so committee panel starts fresh
        for sub in ["reviews", "committee", "decision", "presentation", "research", "criteria", "logs"]:
            p = WORKSPACE_DIR / sub
            if p.exists():
                import shutil as _ws_shutil
                _ws_shutil.rmtree(p, ignore_errors=True)
        yield f"data: {json.dumps({'type': 'workspace_clear'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'start', 'sector': sector}, ensure_ascii=False)}\n\n"

        for key, info in QUERIES.items():
            yield f"data: {json.dumps({'type': 'progress', 'key': key, 'status': 'running'}, ensure_ascii=False)}\n\n"
            try:
                question = info["question"].format(sector=sector)
                answer = await run_nlm_query(question)
                results[key] = answer

                (OUTPUT_DIR / f"{key}_{info['step']}.md").write_text(
                    f"# {info['title']}\n\n**영역:** {sector}\n\n---\n\n{answer}",
                    encoding="utf-8",
                )

                payload = json.dumps(
                    {"type": "result", "key": key, "title": info["title"], "content": answer},
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

            except asyncio.TimeoutError:
                msg = "NotebookLM 응답 시간 초과 (180s)"
                _err_log.error(f"[{key}] {msg}")
                yield f"data: {json.dumps({'type': 'error', 'key': key, 'message': msg}, ensure_ascii=False)}\n\n"
            except Exception as e:
                msg = str(e) or f"{type(e).__name__}"
                _err_log.error(f"[{key}] {msg}\n{traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'error', 'key': key, 'message': msg}, ensure_ascii=False)}\n\n"

        if results:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            parts = [f"# NeoFirm 과제 전체 보고서\n\n**영역:** {sector}\n**생성:** {ts}\n"]
            for key, info in QUERIES.items():
                if key in results:
                    parts.append(f"\n---\n\n# {info['title']}\n\n{results[key]}\n")
            (OUTPUT_DIR / "전체보고서.md").write_text("\n".join(parts), encoding="utf-8")

            # PPTX 자동 생성
            try:
                pptx_path = await asyncio.get_event_loop().run_in_executor(
                    _executor, _build_pptx, sector, results, ts
                )
                pptx_name = pptx_path.name
                yield f"data: {json.dumps({'type': 'pptx', 'filename': pptx_name}, ensure_ascii=False)}\n\n"
                _err_log.info(f"PPTX generated: {pptx_path}")
            except Exception as e:
                _err_log.error(f"PPTX generation failed: {e}\n{traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'pptx_error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        # ── AI 투자위원회 파이프라인 ──────────────────────────────
        if results:
            yield f"data: {json.dumps({'type': 'committee_start'}, ensure_ascii=False)}\n\n"
            try:
                committee_result = await asyncio.get_event_loop().run_in_executor(
                    _executor, _run_committee_sync, sector, results
                )
                yield f"data: {json.dumps({'type': 'committee_done', **committee_result}, ensure_ascii=False)}\n\n"
            except Exception as e:
                _err_log.error(f"Committee pipeline failed: {e}\n{traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'committee_error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Committee Pipeline helpers
# ---------------------------------------------------------------------------

def _committee_call_claude(sys_prompt: str, user_msg: str,
                            model: str = "claude-haiku-4-5-20251001",
                            max_tokens: int = 2048) -> str:
    import httpx, time

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={gemini_key}",
                    headers={"content-type": "application/json"},
                    json={
                        "system_instruction": {"parts": [{"text": sys_prompt}]},
                        "contents": [{"parts": [{"text": user_msg}]}],
                        "generationConfig": {"maxOutputTokens": max_tokens},
                    },
                    timeout=120,
                )
                if resp.status_code == 200:
                    parts = resp.json()["candidates"][0]["content"]["parts"]
                    text = next((p["text"] for p in parts if "text" in p), "")
                    if text:
                        return text.strip()
                    _err_log.warning(f"Gemini 빈 응답 (시도 {attempt+1}/3)")
                elif resp.status_code == 503:
                    _err_log.warning(f"Gemini 503 (시도 {attempt+1}/3), {5*(attempt+1)}초 후 재시도")
                    time.sleep(5 * (attempt + 1))
                else:
                    _err_log.warning(f"Gemini API {resp.status_code}: {resp.text[:200]}")
                    break
            except Exception as e:
                _err_log.warning(f"Gemini 호출 실패 (시도 {attempt+1}/3): {e}")
                time.sleep(3)

    raise RuntimeError("Gemini API 응답 실패 — 위원회 분석을 완료할 수 없습니다 (잠시 후 재시도)")


def _committee_extract_score(text: str) -> dict:
    import re
    CRITERIA = [
        "problem_severity", "customer_evidence", "market_opportunity",
        "differentiation", "technical_feasibility", "execution_feasibility",
        "business_model", "scalability", "risk", "evidence_quality",
    ]
    scores = {}
    for crit in CRITERIA:
        display = crit.replace("_", " ")
        for pat in [
            rf"\|\s*{re.escape(display)}\s*\|\s*(\d)\s*\|",
            rf"\|\s*{re.escape(crit)}\s*\|\s*(\d)\s*\|",
            rf"{re.escape(crit)}\s*[:|]\s*(\d)",
            rf"{re.escape(display)}\s*[:|]\s*(\d)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m and 1 <= int(m.group(1)) <= 5:
                scores[crit] = int(m.group(1))
                break
    return scores


def _committee_extract_decision(text: str) -> str:
    import re
    for pat in [
        r"\*\*Decision:\*\*\s*(INVEST|HOLD|PASS)",
        r"Provisional Decision:\s*\*?\*?(INVEST|HOLD|PASS)",
        r"\*\*(INVEST|HOLD|PASS)\*\*",
        r"\b(INVEST|HOLD|PASS)\b",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return "HOLD"


def _committee_bullets(text: str, n: int = 6) -> list:
    import re
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or "|" in line or line.startswith("---"):
            continue
        line = re.sub(r"^[-•*▸]\s*", "", line).strip()
        line = re.sub(r"^\d+\.\s*", "", line).strip()
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        if len(line) > 10:
            out.append(line)
        if len(out) >= n:
            break
    return out


def _run_committee_sync(sector: str, results: dict) -> dict:
    """
    Full AI investment committee pipeline.
    Runs synchronously in a thread pool.
    Returns dict with: decision, pptx_filename, investment_memo (preview).
    """
    from concurrent.futures import ThreadPoolExecutor as _TPE

    # Build research context from A/B/C/D outputs
    research = f"# 연구 대상\n전문서비스 영역: **{sector}**\n\n"
    for key, info in QUERIES.items():
        if key in results:
            research += f"## {info['title']}\n\n{results[key]}\n\n---\n\n"

    # Load reviewer prompts
    cfg = json.loads(
        (BASE_DIR / "task2_neofirm" / "agents" / "reviewers.json").read_text(encoding="utf-8")
    )
    user_msg = f"## Research Material\n\n{research}"

    # Step 1: 3 reviewers in parallel
    with _TPE(max_workers=3) as pool:
        futs = {
            "market":     pool.submit(_committee_call_claude, cfg["market_reviewer"]["prompt"], user_msg),
            "technology": pool.submit(_committee_call_claude, cfg["technology_reviewer"]["prompt"], user_msg),
            "business":   pool.submit(_committee_call_claude, cfg["business_reviewer"]["prompt"], user_msg),
        }
        reviews = {name: fut.result() for name, fut in futs.items()}

    rev_dir = WORKSPACE_DIR / "reviews"
    rev_dir.mkdir(parents=True, exist_ok=True)
    for name, text in reviews.items():
        (rev_dir / f"{name}_review.md").write_text(text, encoding="utf-8")

    # Step 2: Scores & decisions
    scores    = {n: _committee_extract_score(t)    for n, t in reviews.items()}
    decisions = {n: _committee_extract_decision(t) for n, t in reviews.items()}

    # Step 3: Disagreements
    disagree = []
    if len(set(decisions.values())) > 1:
        disagree.append({
            "id": "D00", "type": "decision",
            "issue": "Reviewers reached different final decisions",
            "reviewer_positions": decisions, "severity": "HIGH",
            "why_it_matters": "Split decision requires committee deliberation.",
        })

    comm_dir = WORKSPACE_DIR / "committee"
    comm_dir.mkdir(exist_ok=True)
    (comm_dir / "disagreements.json").write_text(
        json.dumps({
            "decisions": decisions, "scores": scores,
            "disagreements": disagree,
            "needs_committee_discussion": bool(disagree),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Step 4: Committee discussion (only if disagreements exist)
    discussion = ""
    if disagree:
        disc_sys = (
            "당신은 NeoFirm AI 투자위원회 사회자입니다. "
            "세 리뷰어 보고서와 이견 목록을 바탕으로 위원회 토론을 한국어 마크다운으로 작성하세요. "
            "각 이견의 해소 여부(RESOLVED / PARTIALLY RESOLVED / UNRESOLVED)를 명시하세요."
        )
        disc_user = (
            f"## 섹터\n{sector}\n\n"
            f"## 시장 리뷰\n{reviews['market'][:1500]}\n\n"
            f"## 기술 리뷰\n{reviews['technology'][:1500]}\n\n"
            f"## 사업 리뷰\n{reviews['business'][:1500]}\n\n"
            f"## 이견\n{json.dumps(disagree, ensure_ascii=False)}"
        )
        discussion = _committee_call_claude(disc_sys, disc_user)
        (comm_dir / "discussion.md").write_text(discussion, encoding="utf-8")

        resolution = _committee_call_claude(
            "위원회 토론을 간략히 요약하고 이견 해소 결과를 정리하세요. 한국어, 마크다운.",
            discussion,
        )
        (comm_dir / "resolution.md").write_text(resolution, encoding="utf-8")

    # Step 5: Final decision
    dec_user = (
        f"## Sector\n{sector}\n\n"
        f"## Market Review\n{reviews['market'][:1500]}\n\n"
        f"## Technology Review\n{reviews['technology'][:1500]}\n\n"
        f"## Business Review\n{reviews['business'][:1500]}\n\n"
        f"## Committee Discussion\n{discussion[:1000]}"
    )
    memo = _committee_call_claude(
        cfg["decision_maker"]["prompt"], dec_user,
        model="claude-sonnet-4-5", max_tokens=3000,
    )
    dec_dir = WORKSPACE_DIR / "decision"
    dec_dir.mkdir(exist_ok=True)
    (dec_dir / "investment_memo.md").write_text(memo, encoding="utf-8")

    final_decision = _committee_extract_decision(memo)

    # Step 6: Build slides_data.json
    slides = []
    label_map = {"A": f"NeoFirm × {sector}", "B": "AI-전문가 작업 배분", "C": "1페이지 투자메모", "D": "문제정의문"}
    for key in ["A", "B", "C", "D"]:
        if key in results:
            slides.append({"title": label_map[key], "key_points": _committee_bullets(results[key]), "badge": ""})
    for rev_name, rev_title in [("market", "시장성 리뷰"), ("technology", "기술성 리뷰"), ("business", "사업성 리뷰")]:
        slides.append({"title": rev_title, "key_points": _committee_bullets(reviews[rev_name]), "badge": ""})
    slides.append({"title": f"최종 결정: {final_decision}", "key_points": _committee_bullets(memo), "badge": final_decision})

    slides_data = {
        "title": "NeoFirm AI Investment Committee",
        "sector": sector,
        "decision": final_decision,
        "scores_by_reviewer": scores,
        "decisions_by_reviewer": decisions,
        "slides": slides,
    }

    pres_dir = WORKSPACE_DIR / "presentation"
    pres_dir.mkdir(exist_ok=True)
    (pres_dir / "slides_data.json").write_text(
        json.dumps(slides_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Step 7: Render PPTX via pptx_renderer
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pptx_renderer",
        str(BASE_DIR / "task2_neofirm" / "scripts" / "pptx_renderer.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in sector)[:30]
    pptx_path = pres_dir / f"final_{safe}_{ts}.pptx"
    mod.render(slides_data, pptx_path)

    return {
        "decision": final_decision,
        "pptx_filename": pptx_path.name,
        "memo_preview": memo[:300],
    }


@app.get("/api/workspace")
async def workspace():
    """Return all Task 2 pipeline artifacts as JSON."""
    def read(rel: str) -> str:
        p = WORKSPACE_DIR / rel
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ""

    # find latest PPTX in workspace/presentation/
    pptx_file = None
    pptx_dir = WORKSPACE_DIR / "presentation"
    if pptx_dir.exists():
        pptxs = sorted(pptx_dir.glob("*.pptx"), key=lambda f: f.stat().st_mtime, reverse=True)
        if pptxs:
            pptx_file = pptxs[0].name

    disagreements_raw = read("committee/disagreements.json")
    try:
        disagreements = json.loads(disagreements_raw) if disagreements_raw else {}
    except Exception:
        disagreements = {}

    # sector + decision from slides_data.json
    sector = ""
    slides_decision = ""
    slides_json_path = WORKSPACE_DIR / "presentation" / "slides_data.json"
    if slides_json_path.exists():
        try:
            slides_data = json.loads(slides_json_path.read_text(encoding="utf-8"))
            sector = slides_data.get("sector", "")
            slides_decision = slides_data.get("decision", "")
        except Exception:
            pass

    return {
        "sector":              sector,
        "slides_decision":     slides_decision,
        "reviews": {
            "market":     read("reviews/market_review.md"),
            "technology": read("reviews/technology_review.md"),
            "business":   read("reviews/business_review.md"),
        },
        "disagreements":       disagreements,
        "committee_discussion": read("committee/discussion.md"),
        "resolution":          read("committee/resolution.md"),
        "investment_memo":     read("decision/investment_memo.md"),
        "pptx_filename":       pptx_file,
    }


@app.get("/api/workspace/download")
async def workspace_download():
    """Download the latest Task 2 PPTX."""
    pptx_dir = WORKSPACE_DIR / "presentation"
    if not pptx_dir.exists():
        raise HTTPException(404, "워크스페이스 PPTX 없음")
    pptxs = sorted(pptx_dir.glob("*.pptx"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not pptxs:
        raise HTTPException(404, "PPTX 파일 없음")
    path = pptxs[0]
    return FileResponse(
        path,
        filename="neofirm_report.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.get("/api/download/{filename:path}")
async def download(filename: str):
    path = (OUTPUT_DIR / filename).resolve()
    if not str(path).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(400, "잘못된 경로입니다")
    if not path.exists():
        raise HTTPException(404, "파일이 없습니다. 먼저 생성을 실행해주세요.")
    media = "application/vnd.openxmlformats-officedocument.presentationml.presentation" if filename.endswith(".pptx") else "text/markdown; charset=utf-8"
    return FileResponse(
        path,
        filename=path.name,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename=\"{path.name}\""},
    )


# ---------------------------------------------------------------------------
# PPTX generation
# ---------------------------------------------------------------------------
def _build_pptx(sector: str, results: dict, ts: str) -> Path:
    """Build a PowerPoint presentation from the 4 generated sections."""
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    NAVY   = RGBColor(0x1a, 0x23, 0x4e)
    WHITE  = RGBColor(0xff, 0xff, 0xff)
    ACCENT = RGBColor(0x26, 0x8b, 0xd2)

    blank_layout = prs.slide_layouts[6]  # completely blank

    def _add_rect(slide, l, t, w, h, fill_rgb):
        from pptx.util import Emu
        shape = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_rgb
        shape.line.fill.background()
        return shape

    def _add_textbox(slide, text, l, t, w, h, size, bold, color, wrap=True, align=PP_ALIGN.LEFT):
        txb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
        txb.word_wrap = wrap
        tf = txb.text_frame
        tf.word_wrap = wrap
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        return txb

    # ── Slide 1: Title ──────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank_layout)
    _add_rect(slide, 0, 0, 13.33, 7.5, NAVY)
    _add_textbox(slide, "NeoFirm 과제 자동 생성 보고서", 1, 1.8, 11.33, 1.2, 36, True, WHITE, align=PP_ALIGN.CENTER)
    _add_textbox(slide, f"전문서비스 영역: {sector}", 1, 3.1, 11.33, 0.8, 22, False, ACCENT, align=PP_ALIGN.CENTER)
    _add_textbox(slide, f"생성일시: {ts}  |  NeoFirm AI 분석 시스템", 1, 4.2, 11.33, 0.6, 14, False, WHITE, align=PP_ALIGN.CENTER)

    # ── Content slides ──────────────────────────────────────────────────
    for key, info in QUERIES.items():
        if key not in results:
            continue
        slide = prs.slides.add_slide(blank_layout)

        # header bar
        _add_rect(slide, 0, 0, 13.33, 1.1, NAVY)
        _add_textbox(slide, info["title"], 0.3, 0.15, 12.0, 0.8, 22, True, WHITE)

        # body text
        body_text = results[key]
        # Truncate to ~2000 chars to fit on slide
        if len(body_text) > 2000:
            body_text = body_text[:1970] + "\n…(이하 생략)"

        _add_textbox(slide, body_text, 0.4, 1.3, 12.5, 5.8, 11, False, RGBColor(0x1a, 0x1a, 0x1a))

    # ── Slide: Summary ──────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank_layout)
    _add_rect(slide, 0, 0, 13.33, 1.1, NAVY)
    _add_textbox(slide, "전체 요약 및 Next Steps", 0.3, 0.15, 12.0, 0.8, 22, True, WHITE)

    def _extract_first_line(text: str, max_len: int = 80) -> str:
        import re
        for line in text.splitlines():
            line = re.sub(r"[#*`|>_~\[\]]+", "", line).strip()
            line = re.sub(r"\s+", " ", line)
            if len(line) > 10:
                return line[:max_len] + ("…" if len(line) > max_len else "")
        return ""

    key_labels = {"A": "가치사슬 해부", "B": "AI-전문가 작업 배분", "C": "1페이지 투자메모", "D": "문제정의문"}
    summary_lines = [f"영역: {sector}", ""]
    for key in ["A", "B", "C", "D"]:
        if key in results:
            snippet = _extract_first_line(results[key])
            summary_lines.append(f"✓ {key}. {key_labels[key]} — {snippet}")
        else:
            summary_lines.append(f"✗ {key}. {key_labels[key]} — 생성 실패")
    summary_lines += ["", f"Next: {sector} 프로토타입 설계 → MVP 개발 → 초기 고객 검증"]
    _add_textbox(slide, "\n".join(summary_lines), 0.4, 1.3, 12.5, 5.5, 14, False, RGBColor(0x1a, 0x1a, 0x1a))

    safe_sector = "".join(c if c.isalnum() or c in "-_ " else "_" for c in sector)[:30]
    fname = f"NeoFirm_{safe_sector}_{datetime.now().strftime('%Y%m%d_%H%M')}.pptx"
    out_path = OUTPUT_DIR / fname
    prs.save(str(out_path))
    return out_path
