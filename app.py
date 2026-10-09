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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"
LOGS_DIR = BASE_DIR / "logs"
NOTEBOOK_ID = "6b8429e2-cc08-466e-b785-ee6c0795112f"

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
    """NLM 없을 때 Claude API로 직접 생성."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("NotebookLM CLI를 찾을 수 없고 ANTHROPIC_API_KEY도 없습니다.")
    try:
        import httpx
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": question}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()
    except Exception as e:
        raise RuntimeError(f"Claude API fallback 실패: {e}")


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
        _err_log.error("nlm timeout after 180s")
        raise RuntimeError("NotebookLM 응답 시간 초과 (180s)")

    stdout_text = result.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stderr_text = result.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()

    _err_log.debug(f"returncode={result.returncode}  stderr={stderr_text[:200]}")
    _err_log.debug(f"stdout (first 300): {stdout_text[:300]}")

    if result.returncode != 0:
        msg = stdout_text.strip() or stderr_text or f"nlm exited with code {result.returncode}"
        _err_log.error(f"nlm failed rc={result.returncode}: {msg[:300]}")
        raise RuntimeError(msg)

    answer = stdout_text.strip()
    for sep in ("\nSources:", "\n\nSources:", "\nConversation ID:", "\n\nConversation ID:"):
        idx = answer.find(sep)
        if idx != -1:
            answer = answer[:idx].strip()
            break

    if not answer:
        raise RuntimeError("nlm이 빈 응답을 반환했습니다")

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

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
    _add_textbox(slide, f"생성일시: {ts}  |  Powered by NotebookLM + Claude Code", 1, 4.2, 11.33, 0.6, 14, False, WHITE, align=PP_ALIGN.CENTER)

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
    summary_lines = [
        f"영역: {sector}",
        "",
        "✓ A. 기존 가치사슬 해부 — 공급자 매출구조·고객 불만 포인트 식별",
        "✓ B. AI-전문가 작업 배분 — 자동화/보조/전담/금지 4분류",
        "✓ C. 1페이지 투자메모 — 시장규모·가격구조·독점데이터 설계",
        "✓ D. 문제정의문 — 타깃 고객·핵심 가치제안·KPI 3종",
        "",
        "Next: 프로토타입 설계 → MVP 개발 → 초기 고객 인터뷰",
    ]
    _add_textbox(slide, "\n".join(summary_lines), 0.4, 1.3, 12.5, 5.5, 14, False, RGBColor(0x1a, 0x1a, 0x1a))

    safe_sector = "".join(c if c.isalnum() or c in "-_ " else "_" for c in sector)[:30]
    fname = f"NeoFirm_{safe_sector}_{datetime.now().strftime('%Y%m%d_%H%M')}.pptx"
    out_path = OUTPUT_DIR / fname
    prs.save(str(out_path))
    return out_path
