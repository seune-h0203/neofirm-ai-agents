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
import threading
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
WORKSPACE_DIR_CLAUDE = BASE_DIR / "task2_neofirm" / "workspace_claude"
NOTEBOOK_ID = "94637bca-8a45-4e2f-85d3-e9d68ae762f0"


def _find_claude_exe() -> str | None:
    # 1. Explicit env var override
    if env_path := os.environ.get("CLAUDE_EXE"):
        if Path(env_path).exists():
            return env_path

    # 2. System PATH (Linux/Mac: 'claude', Windows: 'claude.exe')
    if found := _shutil.which("claude"):
        return found

    # 3. Windows: VSCode extension native binary
    ext_base = Path.home() / ".vscode" / "extensions"
    if ext_base.exists():
        for d in sorted(ext_base.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"), reverse=True):
            if d.exists():
                return str(d)

    # 4. Common install locations
    candidates = [
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/usr/bin/claude"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    return None

CLAUDE_EXE = _find_claude_exe()

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


def _inject_nlm_cookies() -> None:
    """
    If NLM_COOKIES_JSON env var is set, write it to the platform-specific
    nlm profile directory so the CLI can authenticate without interactive login.
    Called once at startup; safe to call on Windows too (no-op if var not set).
    """
    import base64
    cookies_b64 = os.environ.get("NLM_COOKIES_JSON", "")
    csrf_token = os.environ.get("NLM_CSRF_TOKEN", "")
    if not cookies_b64:
        return
    try:
        from platformdirs import user_data_dir
        profile_dir = Path(user_data_dir("nlm", "nlm")) / "profiles" / "default"
    except ImportError:
        # fallback: ~/.local/share/nlm/nlm/profiles/default
        profile_dir = Path.home() / ".local" / "share" / "nlm" / "nlm" / "profiles" / "default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        cookies_json = base64.b64decode(cookies_b64).decode("utf-8")
        (profile_dir / "cookies.json").write_text(cookies_json, encoding="utf-8")
        # Leave csrf_token empty so nlm always extracts a fresh one from
        # notebook.google.com at startup (stored token may be stale).
        metadata = json.dumps({
            "csrf_token": "",
            "session_id": "",
            "email": None,
            "last_validated": datetime.now().isoformat(),
        })
        (profile_dir / "metadata.json").write_text(metadata, encoding="utf-8")
        _err_log.info(f"NLM cookies injected → {profile_dir}")
    except Exception as e:
        _err_log.warning(f"NLM cookie injection failed: {e}")


# Module-level auth cache populated by _prefetch_nlm_csrf() at startup
_NLM_AUTH: dict = {"csrf": "", "sid": "", "bl": ""}
# Set True when notebook page redirects to login (cookies expired); skips NLM attempts
_NLM_AUTH_EXPIRED: bool = False


def _prefetch_nlm_csrf() -> str | None:
    """
    Fetch a fresh CSRF token from notebook.google.com.
    Also checks whether the notebook-specific page is accessible (cookie validity).
    Sets _NLM_AUTH_EXPIRED=True if cookies are expired (notebook page redirects to login).
    Returns the new CSRF or None on failure.
    """
    global _NLM_AUTH_EXPIRED
    try:
        from platformdirs import user_data_dir
        profile_dir = Path(user_data_dir("nlm", "nlm")) / "profiles" / "default"
    except ImportError:
        profile_dir = Path.home() / ".local" / "share" / "nlm" / "nlm" / "profiles" / "default"

    cookies_path = profile_dir / "cookies.json"
    if not cookies_path.exists():
        _NLM_AUTH_EXPIRED = True
        return None
    try:
        import re
        import httpx
        cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cookie": cookie_str,
        }
        resp = httpx.get("https://notebook.google.com/", headers=headers,
                         follow_redirects=True, timeout=15)
        if "accounts.google.com" in str(resp.url) or resp.status_code != 200:
            _err_log.warning(f"NLM CSRF prefetch: root redirected to {resp.url} — cookies expired")
            _NLM_AUTH_EXPIRED = True
            return None
        html = resp.text
        csrf_match = re.search(r'"SNlM0e":"([^"]+)"', html)
        if not csrf_match:
            csrf_match = re.search(r'"WZsZ1e":"([^"]{10,})"', html)
        sid_match = re.search(r'"FdrFJe":"([^"]+)"', html)
        bl_match = re.search(r'"KjTSIf":"([^"]*boq_labs-tailwind-frontend_[^"]+)"', html)
        if not bl_match:
            bl_match = re.search(r'"([^"]*boq_labs-tailwind-frontend_[^"]+)"', html)
        new_csrf = csrf_match.group(1) if csrf_match else None
        new_sid = sid_match.group(1) if sid_match else ""
        new_bl = bl_match.group(1) if bl_match else None

        # Verify notebook-specific page is accessible (actual auth check)
        try:
            nb_resp = httpx.get(
                f"https://notebook.google.com/notebook/{NOTEBOOK_ID}",
                headers=headers, follow_redirects=True, timeout=15,
            )
            if "accounts.google.com" in str(nb_resp.url):
                _err_log.warning("NLM auth: notebook page requires login — NLM_COOKIES_JSON is expired")
                _err_log.warning("Research will use Gemini API until NLM_COOKIES_JSON is refreshed")
                _NLM_AUTH_EXPIRED = True
                return None
            _NLM_AUTH_EXPIRED = False
        except Exception as nb_e:
            _err_log.warning(f"NLM notebook page check failed: {nb_e} — assuming cookies valid")

        if new_csrf:
            metadata = json.dumps({
                "csrf_token": new_csrf,
                "session_id": new_sid or "",
                "email": None,
                "last_validated": datetime.now().isoformat(),
            })
            (profile_dir / "metadata.json").write_text(metadata, encoding="utf-8")
            _err_log.info(f"NLM CSRF prefetched OK (len={len(new_csrf)}, bl={new_bl})")
            _NLM_AUTH["csrf"] = new_csrf
            _NLM_AUTH["sid"] = new_sid or ""
        if new_bl:
            os.environ["NOTEBOOKLM_BL"] = new_bl
            _NLM_AUTH["bl"] = new_bl
        return new_csrf
    except Exception as e:
        _err_log.warning(f"NLM CSRF prefetch failed: {e}")
        return None


def _parse_nlm_answer(response_text: str) -> str:
    """Extract final answer frames, excluding protocol IDs and thinking frames."""
    import re
    answers = []
    for line in response_text.removeprefix(")]}'").splitlines():
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, list):
            continue
        for chunk in data:
            if not isinstance(chunk, list) or len(chunk) < 3 or chunk[0] != "wrb.fr" or not isinstance(chunk[2], str):
                continue
            try:
                parsed = json.loads(chunk[2])
                first = parsed[0]
                text = first[0]
                if not isinstance(first, list) or not isinstance(text, str) or len(text.strip()) <= 20:
                    continue
                if re.fullmatch(r"[0-9a-fA-F-]{36}", text.strip()):
                    continue
                if len(first) > 4 and isinstance(first[4], list) and first[4] and isinstance(first[4][-1], int) and first[4][-1] != 1:
                    continue
                answers.append(text.strip())
            except (ValueError, TypeError, IndexError):
                continue
    # The installed NotebookLM client selects the final completed answer frame.
    return answers[-1] if answers else ""


async def _nlm_query_async(question: str, notebook_id: str) -> str:
    """
    Query NotebookLM directly via async httpx — bypasses the NLM library's
    synchronous httpx client which fails on Railway.
    Returns the answer text or raises RuntimeError.
    """
    import re
    import urllib.parse
    import httpx

    try:
        from platformdirs import user_data_dir as _udd
        profile_dir = Path(_udd("nlm", ensure_exists=False)) / "profiles" / "default"
    except ImportError:
        profile_dir = Path.home() / ".local" / "share" / "nlm" / "nlm" / "profiles" / "default"

    cookies_path = profile_dir / "cookies.json"
    if not cookies_path.exists():
        raise RuntimeError("NLM cookies not found — set NLM_COOKIES_JSON env var")

    cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

    base_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Cookie": cookie_str,
    }
    rpc_headers = {
        **base_headers,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": "https://notebook.google.com",
        "Referer": "https://notebook.google.com/",
        "X-Same-Domain": "1",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        # Step 1: Use CSRF from startup cache (_prefetch_nlm_csrf writes it at server start)
        csrf = _NLM_AUTH.get("csrf", "")
        session_id = _NLM_AUTH.get("sid", "")
        bl = _NLM_AUTH.get("bl", "") or os.environ.get("NOTEBOOKLM_BL", "boq_labs-tailwind-frontend_20261011.03_p0")
        if not csrf:
            # Fallback: try to load from metadata.json (written at startup by _prefetch_nlm_csrf)
            meta_path = profile_dir / "metadata.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    csrf = meta.get("csrf_token", "")
                    session_id = session_id or meta.get("session_id", "")
                except Exception:
                    pass
        if not csrf:
            # On-demand prefetch: startup may have failed — try now
            _err_log.info("_nlm_query_async: CSRF empty, running on-demand prefetch")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _prefetch_nlm_csrf)
            csrf = _NLM_AUTH.get("csrf", "")
            session_id = _NLM_AUTH.get("sid", "") or session_id
            bl = _NLM_AUTH.get("bl", "") or bl
            if not csrf:
                raise RuntimeError("NLM CSRF token not available — on-demand prefetch also failed")

        def _make_body(rpc_id: str, params: object, extra_csrf: str = "") -> str:
            p = json.dumps(params, separators=(',', ':'))
            f_req = json.dumps([[[rpc_id, p, None, "generic"]]], separators=(',', ':'))
            parts = [f"f.req={urllib.parse.quote(f_req, safe='')}"]
            _c = extra_csrf or csrf
            if _c:
                parts.append(f"at={urllib.parse.quote(_c, safe='')}")
            return "&".join(parts) + "&"

        def _make_url(rpc_id: str, source_path: str = "/") -> str:
            p = {"rpcids": rpc_id, "source-path": source_path,
                 "bl": bl, "hl": "en", "rt": "c"}
            if session_id:
                p["f.sid"] = session_id
            return f"https://notebook.google.com/_/LabsTailwindUi/data/batchexecute?{urllib.parse.urlencode(p)}"

        # Step 2: Get notebook sources (GET_NOTEBOOK RPC)
        nb_resp = await client.post(
            _make_url("rLM1Ne", f"/notebook/{notebook_id}"),
            content=_make_body("rLM1Ne", [notebook_id, None, [2], None, 0]),
            headers=rpc_headers,
        )
        source_ids = []
        if nb_resp.status_code == 200:
            # Parse batchexecute response for source IDs
            # Structure: [["wrb.fr","rLM1Ne","[[title, sources_data, nb_id, ...]]",...]]
            # sources_data = [[src[0]=[src_id], src[1]=title, src[2]=metadata], ...]
            for line in nb_resp.text.split("\n"):
                try:
                    chunk = json.loads(line)
                    if isinstance(chunk, list):
                        for item in chunk:
                            if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr" and item[1] == "rLM1Ne":
                                result = json.loads(item[2]) if isinstance(item[2], str) else item[2]
                                if isinstance(result, list) and result:
                                    nb_entry = result[0]  # [title, sources_data, nb_id, ...]
                                    if isinstance(nb_entry, list) and len(nb_entry) > 1:
                                        sources_data = nb_entry[1] or []  # sources at index 1
                                        for s in sources_data:
                                            # s = [[src_id], title, metadata, ...]
                                            if isinstance(s, list) and s and isinstance(s[0], list) and s[0]:
                                                source_ids.append(s[0][0])
                except Exception:
                    pass

        # Step 3: Query the notebook
        import uuid
        import random
        conversation_id = str(uuid.uuid4())
        sources_array = [[[sid]] for sid in source_ids] if source_ids else []
        q_params = [sources_array, question, None, [2, None, [1]], conversation_id]
        q_params_json = json.dumps(q_params, separators=(',', ':'))
        # GenerateFreeFormStreamed uses [null, params_json] (NOT batchexecute's [[[rpc_id, ...]]])
        f_req_q = json.dumps([None, q_params_json], separators=(',', ':'))
        q_body_parts = [f"f.req={urllib.parse.quote(f_req_q, safe='')}"]
        if csrf:
            q_body_parts.append(f"at={urllib.parse.quote(csrf, safe='')}")
        q_body = "&".join(q_body_parts) + "&"
        q_url_p = {"bl": bl, "hl": "en", "_reqid": str(random.randint(100000, 999999)), "rt": "c"}
        if session_id:
            q_url_p["f.sid"] = session_id
        q_endpoint = "/_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
        q_url = f"https://notebook.google.com{q_endpoint}?{urllib.parse.urlencode(q_url_p)}"

        q_resp = await client.post(q_url, content=q_body, headers=rpc_headers, timeout=90)
        q_resp.raise_for_status()

        answer = _parse_nlm_answer(q_resp.text)
        if not answer:
            raw_preview = q_resp.text[:1500]
            raise RuntimeError(f"NLM parsing failed. source_ids={source_ids!r}. raw={raw_preview!r}")
        return answer



_inject_nlm_cookies()
_prefetch_nlm_csrf()
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


_gemini_request_lock = threading.Lock()


def _call_gemini_text(question: str, system: str = "", max_tokens: int = 3072) -> str:
    import httpx
    import time

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다")
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite").removeprefix("models/")
    body = {
        "contents": [{"parts": [{"text": question}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    for attempt in range(3):
        try:
            # Avoid bursts from the three reviewer workers sharing one API quota.
            with _gemini_request_lock:
                resp = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key, "content-type": "application/json"},
                    json=body, timeout=120,
                )
        except httpx.TimeoutException:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError("Gemini 응답 시간 초과 — 잠시 후 다시 시도해주세요") from None
        if resp.status_code == 200:
            candidates = resp.json().get("candidates", [])
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            text = "\n".join(p["text"] for p in parts if p.get("text") and not p.get("thought"))
            if text.strip():
                return text.strip()
            raise RuntimeError("Gemini가 빈 응답을 반환했습니다")
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            delay = 30 * (attempt + 1) if resp.status_code == 429 else 3 * (attempt + 1)
            if resp.status_code == 429:
                for detail in resp.json().get("error", {}).get("details", []):
                    retry_delay = detail.get("retryDelay", "")
                    if isinstance(retry_delay, str) and retry_delay.endswith("s"):
                        try:
                            delay = max(delay, float(retry_delay[:-1]))
                        except ValueError:
                            pass
            time.sleep(min(delay, 60))
            continue
        _err_log.error("Gemini HTTP %s (model=%s)", resp.status_code, model)
        if resp.status_code == 404:
            raise RuntimeError(f"Gemini 모델을 사용할 수 없습니다: {model}. GEMINI_MODEL 설정을 확인해주세요")
        raise RuntimeError(f"Gemini API 오류 ({resp.status_code}) — 키, 사용량 또는 서비스 상태를 확인해주세요")
    raise RuntimeError("Gemini 응답 실패")


# ── Anthropic API direct HTTP call ────────────────────────────────────────────

def _call_anthropic_text(question: str, system: str = "", max_tokens: int = 2048) -> str:
    """Call Anthropic Claude API directly via httpx (no CLI required)."""
    import httpx
    import time

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다")
    model = os.environ.get("CLAUDE_API_MODEL", "claude-sonnet-4-5")
    messages = [{"role": "user", "content": question}]
    body: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        body["system"] = system

    for attempt in range(3):
        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
                timeout=180,
            )
        except httpx.TimeoutException:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError("Anthropic API 응답 시간 초과 — 잠시 후 다시 시도해주세요") from None
        if resp.status_code == 200:
            content = resp.json().get("content", [])
            text = "\n".join(b["text"] for b in content if b.get("type") == "text" and b.get("text"))
            if text.strip():
                return text.strip()
            raise RuntimeError("Claude API가 빈 응답을 반환했습니다")
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            delay = 30 * (attempt + 1) if resp.status_code == 429 else 5 * (attempt + 1)
            try:
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    delay = max(delay, float(retry_after))
            except (ValueError, TypeError):
                pass
            time.sleep(min(delay, 60))
            continue
        _err_log.error("Anthropic API HTTP %s (model=%s): %s", resp.status_code, model, resp.text[:200])
        if resp.status_code == 401:
            raise RuntimeError("ANTHROPIC_API_KEY 인증 실패 — 키를 확인해주세요")
        if resp.status_code == 529:
            raise RuntimeError("Anthropic API 과부하 — 잠시 후 다시 시도해주세요")
        raise RuntimeError(f"Anthropic API 오류 ({resp.status_code}) — 키, 사용량 또는 서비스 상태를 확인해주세요")
    raise RuntimeError("Anthropic API 응답 실패")


def _gemini_research_fallback(question: str) -> str:
    """Gemini-based research for NeoFirm assignment analysis."""
    sys_prompt = (
        "당신은 한국 전문서비스 산업 전문 리서처이자 NeoFirm 과제 작성 전문가입니다. "
        "아래 질문에 대해 다음 기준을 철저히 따르세요:\n"
        "- 구체적인 수치, 사례, 시장 데이터를 포함하세요\n"
        "- 한국 시장 현실을 반영하세요\n"
        "- 반드시 한국어로 답변하세요 (영어 원문이 있어도 번역)\n"
        "- 표나 bullet 형식으로 명확하게 정리하세요\n"
        "- 각 항목에 실질적인 분석과 근거를 제시하세요"
    )
    return _call_gemini_text(question, system=sys_prompt, max_tokens=4096)


def _run_nlm_sync(question: str) -> str:
    """
    Synchronous nlm call — runs in a thread so Windows SelectorEventLoop works.
    Falls back to Claude API if nlm is not available.
    Raises RuntimeError on failure.
    """
    nlm_path = NLM
    if not nlm_path:
        _err_log.warning("nlm not found — Gemini로 연구 조사 대체")
        return _gemini_research_fallback(question)

    # Pre-fetch a fresh CSRF token so nlm doesn't call its own _refresh_auth_tokens()
    # (which uses Sec-Fetch-* headers that trigger Google's re-auth redirect on cloud IPs).
    _prefetch_nlm_csrf()

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
        _err_log.error("nlm timeout after 180s — Gemini로 연구 조사 대체")
        return _gemini_research_fallback(question)

    stdout_text = result.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stderr_text = result.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()

    _err_log.debug(f"returncode={result.returncode}  stderr={stderr_text[:200]}")
    _err_log.debug(f"stdout (first 300): {stdout_text[:300]}")

    # nlm exits with code 255 on success — treat 0 and 255 as success, anything else as failure.
    # Also treat success-code exits as failure if the output starts with an error string.
    is_error_output = stdout_text.strip().startswith("Error:")
    if result.returncode not in (0, 255) or is_error_output:
        msg = stdout_text.strip() or stderr_text or f"nlm exited with code {result.returncode}"
        _err_log.error(f"nlm failed rc={result.returncode}: {msg[:300]}")
        _err_log.warning("nlm 실패 — Gemini로 연구 조사 대체")
        return _gemini_research_fallback(question)

    answer = stdout_text.strip()
    for sep in ("\nSources:", "\n\nSources:", "\nConversation ID:", "\n\nConversation ID:"):
        idx = answer.find(sep)
        if idx != -1:
            answer = answer[:idx].strip()
            break

    # 출력이 아예 Conversation ID로 시작하면 실제 답변 없음
    if answer.startswith("Conversation ID:") or answer.startswith("Use --conversation-id"):
        answer = ""

    if not answer:
        _err_log.warning("nlm 빈 응답 — Gemini로 연구 조사 대체")
        return _gemini_research_fallback(question)

    return answer


# ---------------------------------------------------------------------------
# Research provider adapter pattern
# ---------------------------------------------------------------------------

class ResearchProvider:
    """Abstract interface for research providers."""
    async def query(self, question: str) -> str:
        raise NotImplementedError


class NotebookLMResearchProvider(ResearchProvider):
    """NotebookLM-based research via batchexecute API."""
    def __init__(self, notebook_id: str):
        self.notebook_id = notebook_id

    async def query(self, question: str) -> str:
        return await _nlm_query_async(question, self.notebook_id)


class GeminiResearchProvider(ResearchProvider):
    """Gemini API-based research with NeoFirm-specific system prompt."""
    async def query(self, question: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, _gemini_research_fallback, question)


async def run_nlm_query(question: str) -> str:
    """Query NotebookLM with automatic Gemini fallback.

    Routes to Gemini immediately if NLM cookies are known to be expired,
    avoiding a failed NLM attempt and 120-second timeout wait.
    """
    # If cookies are confirmed expired at startup, skip NLM entirely
    if _NLM_AUTH_EXPIRED:
        _err_log.info("NLM auth expired — routing research to Gemini")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, _gemini_research_fallback, question)

    if platform.system() != "Windows" and os.environ.get("NLM_COOKIES_JSON"):
        try:
            return await asyncio.wait_for(
                _nlm_query_async(question, NOTEBOOK_ID),
                timeout=120,
            )
        except Exception as e:
            _err_log.warning(f"NLM async query failed: {e} — Gemini로 대체")
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(_executor, _gemini_research_fallback, question)
    # Windows / no cookies: subprocess path
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
            "한국어로, 표나 bullet 형식으로 정리해줘. "
            "**중요: 영어 원문 자료가 있더라도 반드시 한국어로 번역해서 답변해줘. 영어 문장을 그대로 포함하지 마.**"
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
            "각 구분마다 구체적인 업무 예시를 3개 이상 포함해줘. 한국어 표 형식. "
            "**중요: 영어 원문 자료가 있더라도 반드시 한국어로 번역해서 답변해줘. 영어 문장을 그대로 포함하지 마.**"
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
            "한국어로, 각 항목을 명확히 구분해서 작성해줘. "
            "**중요: 영어 원문 자료가 있더라도 반드시 한국어로 번역해서 답변해줘. 영어 문장을 그대로 포함하지 마.**"
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
            "- 첫 번째 KPI 3가지\n"
            "**중요: 영어 원문 자료가 있더라도 반드시 한국어로 번역해서 답변해줘. 영어 문장을 그대로 포함하지 마.**"
        ),
    },
}

async def _with_run_status(stream, expected_committees: int = 1, require_comparison: bool = False):
    """An SSE connection ending does not imply that its pipeline succeeded."""
    research = set()
    committees = set()
    errors = 0
    research_pptx = False
    comparison = False
    async for chunk in stream:
        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            kind = event.get("type", "")
            if kind == "result":
                research.add(event["key"])
            elif kind == "pptx":
                research_pptx = bool(event.get("filename"))
            elif kind == "committee_done" and event.get("pptx_filename"):
                committees.add(event.get("engine", "gemini"))
            elif kind == "comparison_done":
                comparison = True
            elif kind == "error" or kind.endswith("_error"):
                errors += 1
            elif kind == "done":
                complete = (len(research) == len(QUERIES) and research_pptx
                            and len(committees) == expected_committees
                            and (comparison or not require_comparison) and errors == 0)
                event.update(status="success" if complete else "partial" if research else "failed",
                             research_completed=len(research), research_failed=len(QUERIES) - len(research),
                             committees_completed=len(committees), errors=errors)
                chunk = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield chunk


app = FastAPI(title="NeoFirm Generator", version="2026.10.13.5")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/runtime")
async def runtime_status():
    cli_installed = bool(CLAUDE_EXE)
    anthropic_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    claude_available = cli_installed and anthropic_key_set
    return {
        "version": app.version,
        "claude_mode": "cli" if claude_available else "unavailable",
        "claude_cli_installed": cli_installed,
        "claude_available": claude_available,
        "claude_model": os.environ.get("CLAUDE_API_MODEL", "claude-sonnet-4-5"),
        "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
    }



@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/debug")
async def debug_info():
    """개발용: nlm 탐색 결과 및 환경 확인."""
    venv_bin = Path(sys.executable).parent
    linux_nlm = venv_bin / "nlm"
    local_nlm = Path.home() / ".local" / "bin" / "nlm"
    try:
        import importlib.util
        nlm_spec = importlib.util.find_spec("notebooklm")
        nlm_pkg = str(nlm_spec) if nlm_spec else None
    except Exception:
        nlm_pkg = None
    return {
        "nlm_path": NLM,
        "nlm_which": _shutil.which("nlm"),
        "python_exe": sys.executable,
        "venv_bin": str(venv_bin),
        "linux_nlm_path": str(linux_nlm),
        "linux_nlm_exists": linux_nlm.exists(),
        "local_bin_nlm_exists": local_nlm.exists(),
        "nlm_pkg_spec": nlm_pkg,
        "PATH": os.environ.get("PATH", "")[:500],
        "NLM_COOKIES_SET": bool(os.environ.get("NLM_COOKIES_JSON")),
        "NLM_CSRF_SET": bool(os.environ.get("NLM_CSRF_TOKEN")),
        "cwd": str(Path.cwd()),
    }


@app.get("/api/debug-cookies")
async def debug_cookies():
    """개발용: NLM 쿠키 주입 경로 및 파일 존재 여부 확인."""
    try:
        from platformdirs import user_data_dir
        profile_dir = Path(user_data_dir("nlm", "nlm")) / "profiles" / "default"
    except ImportError:
        profile_dir = Path.home() / ".local" / "share" / "nlm" / "nlm" / "profiles" / "default"
    cookies_path = profile_dir / "cookies.json"
    metadata_path = profile_dir / "metadata.json"
    cookies_content = None
    if cookies_path.exists():
        try:
            raw = cookies_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            cookies_content = {"keys": list(data.keys()) if isinstance(data, dict) else "list_len=" + str(len(data)), "size": len(raw)}
        except Exception as e:
            cookies_content = {"error": str(e)}
    return {
        "profile_dir": str(profile_dir),
        "cookies_exists": cookies_path.exists(),
        "metadata_exists": metadata_path.exists(),
        "cookies_info": cookies_content,
        "platform": platform.system(),
        "home": str(Path.home()),
    }


@app.get("/api/test-batchexecute")
async def test_batchexecute():
    """개발용: batchexecute API 직접 호출 - raw 응답 반환."""
    import re
    import httpx
    import urllib.parse

    try:
        from platformdirs import user_data_dir as _udd
        profile_dir = Path(_udd("nlm", ensure_exists=False)) / "profiles" / "default"
    except ImportError:
        profile_dir = Path.home() / ".local" / "share" / "nlm" / "nlm" / "profiles" / "default"

    cookies_path = profile_dir / "cookies.json"
    metadata_path = profile_dir / "metadata.json"

    if not cookies_path.exists():
        return {"error": "cookies.json not found"}

    cookies = json.loads(cookies_path.read_text())
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    csrf = metadata.get("csrf_token", "")
    session_id = metadata.get("session_id", "")

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

    # Build batchexecute request (same as NLM's _call_rpc)
    rpc_id = "rLM1Ne"  # GET_NOTEBOOK
    notebook_id = NOTEBOOK_ID
    params = [notebook_id, None, [2], None, 0]
    params_json = json.dumps(params, separators=(',', ':'))
    f_req = [[[rpc_id, params_json, None, "generic"]]]
    f_req_json = json.dumps(f_req, separators=(',', ':'))

    body_parts = [f"f.req={urllib.parse.quote(f_req_json, safe='')}"]
    if csrf:
        body_parts.append(f"at={urllib.parse.quote(csrf, safe='')}")
    body = "&".join(body_parts) + "&"

    bl = os.environ.get("NOTEBOOKLM_BL", "boq_labs-tailwind-frontend_20260108.06_p0")
    url_params = {"rpcids": rpc_id, "source-path": f"/notebook/{notebook_id}", "bl": bl, "hl": "en", "rt": "c"}
    if session_id:
        url_params["f.sid"] = session_id
    url = f"https://notebook.google.com/_/LabsTailwindUi/data/batchexecute?{urllib.parse.urlencode(url_params)}"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": "https://notebook.google.com",
        "Referer": "https://notebook.google.com/",
        "Cookie": cookie_str,
        "X-Same-Domain": "1",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, content=body, headers=headers)

    return {
        "status_code": resp.status_code,
        "has_csrf": bool(csrf),
        "csrf_len": len(csrf) if csrf else 0,
        "has_session_id": bool(session_id),
        "bl": bl,
        "response_text": resp.text[:1500],
        "response_headers": dict(list(resp.headers.items())[:5])
    }


@app.get("/api/debug-csrf-prefetch")
async def debug_csrf_prefetch():
    """개발용: _prefetch_nlm_csrf 실행 결과 + HTML 진단."""
    import re, httpx
    try:
        from platformdirs import user_data_dir as _udd
        profile_dir = Path(_udd("nlm", "nlm")) / "profiles" / "default"
    except ImportError:
        profile_dir = Path.home() / ".local" / "share" / "nlm" / "nlm" / "profiles" / "default"

    cookies_path = profile_dir / "cookies.json"
    if not cookies_path.exists():
        return {"error": "cookies.json not found", "profile_dir": str(profile_dir)}

    cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cookie": cookie_str,
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get("https://notebook.google.com/", headers=headers)
            html = resp.text
            csrf_m = re.search(r'"SNlM0e":"([^"]+)"', html)
            if not csrf_m:
                csrf_m = re.search(r'"WZsZ1e":"([^"]{10,})"', html)
            bl_m = re.search(r'"KjTSIf":"([^"]*boq_labs-tailwind-frontend_[^"]+)"', html)
            if not bl_m:
                bl_m = re.search(r'"([^"]*boq_labs-tailwind-frontend_[^"]+)"', html)
            # Also try notebook-specific page for SNlM0e
            nb_resp = await client.get(f"https://notebook.google.com/notebook/{NOTEBOOK_ID}", headers=headers)
            nb_html = nb_resp.text
            nb_csrf_m = re.search(r'"SNlM0e":"([^"]+)"', nb_html)
            if not nb_csrf_m:
                nb_csrf_m = re.search(r'"WZsZ1e":"([^"]{10,})"', nb_html)
        return {
            "root_status": resp.status_code,
            "root_html_len": len(html),
            "root_csrf_key": "SNlM0e" if re.search(r'"SNlM0e"', html) else ("WZsZ1e" if re.search(r'"WZsZ1e"', html) else "none"),
            "root_csrf": csrf_m.group(1)[:30] if csrf_m else None,
            "nb_status": nb_resp.status_code,
            "nb_url": str(nb_resp.url),
            "nb_html_len": len(nb_html),
            "nb_csrf_key": "SNlM0e" if re.search(r'"SNlM0e"', nb_html) else ("WZsZ1e" if re.search(r'"WZsZ1e"', nb_html) else "none"),
            "nb_csrf": nb_csrf_m.group(1)[:30] if nb_csrf_m else None,
            "bl": bl_m.group(1) if bl_m else None,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/test-google-access")
async def test_google_access():
    """개발용: Google 서버 접근 가능 여부 확인 (IP 차단 진단)."""
    import httpx
    try:
        # Read injected cookies
        from platformdirs import user_data_dir as _udd
        profile_dir = Path(_udd("nlm", ensure_exists=False)) / "profiles" / "default"
        cookies_path = profile_dir / "cookies.json"
        if not cookies_path.exists():
            return {"error": "cookies.json not found"}
        cookies = json.loads(cookies_path.read_text())
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

        headers = {
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get("https://notebook.google.com/", headers=headers)
            return {
                "final_url": str(resp.url),
                "status_code": resp.status_code,
                "is_auth_redirect": "accounts.google.com" in str(resp.url),
                "cookies_valid": "accounts.google.com" not in str(resp.url) and resp.status_code == 200,
            }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/nlm-status")
async def nlm_status():
    """NotebookLM 인증 상태 및 현재 리서치 공급자 확인."""
    provider = "gemini"
    if not _NLM_AUTH_EXPIRED and os.environ.get("NLM_COOKIES_JSON") and platform.system() != "Windows":
        provider = "notebooklm"
    return {
        "research_provider": provider,
        "nlm_cookies_set": bool(os.environ.get("NLM_COOKIES_JSON")),
        "nlm_auth_expired": _NLM_AUTH_EXPIRED,
        "nlm_csrf_cached": bool(_NLM_AUTH.get("csrf")),
        "gemini_api_set": bool(os.environ.get("GEMINI_API_KEY")),
        "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "nlm_refresh_required": _NLM_AUTH_EXPIRED,
        "nlm_refresh_instructions": (
            "NLM 쿠키 만료됨. 브라우저에서 notebook.google.com 로그인 후 쿠키를 JSON으로 내보내고 "
            "Base64 인코딩하여 Railway 환경 변수 NLM_COOKIES_JSON을 업데이트하세요."
        ) if _NLM_AUTH_EXPIRED else None,
    }


@app.get("/api/test-nlm-python")
async def test_nlm_python():
    """개발용: 프리페치된 CSRF로 NLM Python 라이브러리 직접 쿼리."""
    try:
        from nlm.core.auth import get_auth_manager
        from nlm.core.client import NotebookLMClient

        loop = asyncio.get_event_loop()

        def _run_nlm_direct():
            # Pre-fetch fresh CSRF first
            fresh_csrf = _prefetch_nlm_csrf()
            if not fresh_csrf:
                return None, "CSRF prefetch failed"

            # Load profile - should now have fresh CSRF
            auth = get_auth_manager()
            profile = auth.load_profile()
            # Pass CSRF explicitly to bypass _refresh_auth_tokens()
            with NotebookLMClient(
                auth_manager=auth,
                csrf_token=profile.csrf_token,
                session_id=profile.session_id or "",
            ) as client:
                result = client.query(
                    NOTEBOOK_ID,
                    "입시컨설팅 시장 규모는?",
                )
                if isinstance(result, dict):
                    return result.get("answer", str(result))[:500], None
                return str(result)[:500] if result else "(empty)", None

        answer, err = await loop.run_in_executor(_executor, _run_nlm_direct)
        if err:
            return {"status": "error", "error": err}
        return {"status": "ok", "answer": answer}
    except Exception as e:
        import traceback
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()[-800:]}


@app.get("/api/test-nlm")
async def test_nlm():
    """개발용: NLM 단일 쿼리 실행 후 raw stdout/stderr/returncode 반환."""
    import asyncio
    nlm_path = NLM
    if not nlm_path:
        return {"error": "nlm not found", "nlm_path": None}

    question = "입시컨설팅 시장 규모는?"
    cmd = [nlm_path, "notebook", "query", NOTEBOOK_ID, question]
    env = _build_env()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60)
        returncode = proc.returncode
        stdout_text = stdout_b.decode("utf-8", errors="replace")
        stderr_text = stderr_b.decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        return {"error": "timeout after 60s"}
    except Exception as e:
        return {"error": str(e)}

    return {
        "returncode": returncode,
        "stdout": stdout_text[:2000],
        "stderr": stderr_text[:2000],
        "nlm_path": nlm_path,
        "notebook_id": NOTEBOOK_ID,
    }


@app.get("/api/test-nlm-async")
async def test_nlm_async():
    """개발용: _nlm_query_async 직접 호출 테스트 (async httpx 경로)."""
    try:
        answer = await asyncio.wait_for(
            _nlm_query_async("입시컨설팅 시장 규모는?", NOTEBOOK_ID),
            timeout=90,
        )
        return {"status": "ok", "answer": answer[:1000]}
    except Exception as e:
        import traceback
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()[-1200:]}


@app.get("/api/debug-nlm-sources")
async def debug_nlm_sources():
    """개발용: GET_NOTEBOOK batchexecute 응답 파싱 단계 디버그."""
    import re, urllib.parse, httpx
    try:
        from platformdirs import user_data_dir as _udd
        profile_dir = Path(_udd("nlm", ensure_exists=False)) / "profiles" / "default"
    except ImportError:
        profile_dir = Path.home() / ".local" / "share" / "nlm" / "nlm" / "profiles" / "default"
    cookies_path = profile_dir / "cookies.json"
    if not cookies_path.exists():
        return {"error": "no cookies"}
    cookies = json.loads(cookies_path.read_text())
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    base_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36", "Cookie": cookie_str}
    async with httpx.AsyncClient(timeout=30) as client:
        page = await client.get("https://notebook.google.com/", headers=base_headers, follow_redirects=True)
        redirected = "accounts.google.com" in str(page.url) or page.status_code != 200
        html = page.text
        csrf_m = re.search(r'"SNlM0e":"([^"]+)"', html)
        sid_m = re.search(r'"FdrFJe":"([^"]+)"', html)
        bl_m = re.search(r'"(boq_labs-tailwind-frontend_[^"]+)"', html)
        csrf = csrf_m.group(1) if csrf_m else ""
        session_id = sid_m.group(1) if sid_m else ""
        bl = bl_m.group(1) if bl_m else os.environ.get("NOTEBOOKLM_BL", "")
        rpc_headers = {**base_headers, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                       "Origin": "https://notebook.google.com", "Referer": "https://notebook.google.com/", "X-Same-Domain": "1"}
        p = json.dumps([NOTEBOOK_ID, None, [2], None, 0], separators=(',', ':'))
        f_req = json.dumps([[["rLM1Ne", p, None, "generic"]]], separators=(',', ':'))
        url_p = {"rpcids": "rLM1Ne", "source-path": f"/notebook/{NOTEBOOK_ID}", "bl": bl, "hl": "en", "rt": "c"}
        if session_id:
            url_p["f.sid"] = session_id
        body = f"f.req={urllib.parse.quote(f_req, safe='')}"
        if csrf:
            body += f"&at={urllib.parse.quote(csrf, safe='')}"
        body += "&"
        nb = await client.post(f"https://notebook.google.com/_/LabsTailwindUi/data/batchexecute?{urllib.parse.urlencode(url_p)}",
                               content=body, headers=rpc_headers)
        lines = nb.text.split("\n")
        parsed_lines = []
        source_ids_found = []
        for line in lines:
            try:
                d = json.loads(line)
                parsed_lines.append({"type": type(d).__name__, "preview": str(d)[:200]})
                if isinstance(d, list):
                    for item in d:
                        if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                            parsed_lines.append({"found_wrb_fr": True, "rpc_id": item[1], "item2_type": type(item[2]).__name__, "item2_preview": str(item[2])[:300]})
                            if item[1] == "rLM1Ne" and isinstance(item[2], str):
                                result = json.loads(item[2])
                                nb_entry = result[0] if result else None
                                if nb_entry and len(nb_entry) > 1:
                                    for s in nb_entry[1]:
                                        if isinstance(s, list) and s and isinstance(s[0], list) and s[0]:
                                            source_ids_found.append(s[0][0])
            except Exception:
                pass
        return {"page_ok": not redirected, "page_url": str(page.url), "csrf": bool(csrf), "bl": bl,
                "nb_status": nb.status_code, "raw_preview": nb.text[:800], "parsed_lines": parsed_lines[:10], "source_ids": source_ids_found}


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
            def _cprog(wf_step: int, status: str, message: str) -> str:
                return f"data: {json.dumps({'type': 'committee_progress', 'wf_step': wf_step, 'status': status, 'message': message}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'committee_start'}, ensure_ascii=False)}\n\n"
            loop = asyncio.get_event_loop()
            try:
                # Phase 1: 3 reviewers
                yield _cprog(2, "run", "시장·기술·사업 리뷰어 독립 평가 중…")
                reviews, scores, decisions, disagree, cfg = await loop.run_in_executor(
                    _executor, _committee_phase1, sector, results
                )
                yield _cprog(2, "done", "리뷰어 평가 완료")
                yield _cprog(3, "done", f"이견 {len(disagree)}건 감지")

                # Phase 2: Discussion
                if disagree:
                    yield _cprog(4, "run", "AI 위원회 토론 진행 중…")
                    discussion, resolution = await loop.run_in_executor(
                        _executor, _committee_phase2, sector, reviews, disagree, cfg
                    )
                    yield _cprog(4, "done", "AI 토론 완료")
                else:
                    discussion, resolution = "", ""
                    yield _cprog(4, "skip", "이견 없음 — 토론 생략")

                # Phase 3: Final decision
                yield _cprog(5, "run", "최종 투자 판단 작성 중…")
                memo, final_decision = await loop.run_in_executor(
                    _executor, _committee_phase3, sector, reviews, discussion, cfg
                )
                yield _cprog(5, "done", f"최종 판단: {final_decision}")

                # Phase 4: PPT
                yield _cprog(6, "run", "위원회 PPT 생성 중…")
                pptx_filename = await loop.run_in_executor(
                    _executor, _committee_phase4, sector, results, reviews, scores, decisions, final_decision, memo
                )
                yield _cprog(6, "done", "위원회 PPT 완료")

                yield f"data: {json.dumps({'type': 'committee_done', 'decision': final_decision, 'pptx_filename': pptx_filename, 'memo_preview': memo[:300]}, ensure_ascii=False)}\n\n"

            except Exception as e:
                _err_log.error(f"Committee pipeline failed: {e}\n{traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'committee_error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _with_run_status(stream()),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Committee Pipeline helpers
# ---------------------------------------------------------------------------

def _committee_call_gemini(sys_prompt: str, user_msg: str,
                            model: str = "gemini", max_tokens: int = 2048) -> str:
    return _call_gemini_text(user_msg, system=sys_prompt, max_tokens=max_tokens)


def _committee_call_claude_cli(sys_prompt: str, user_msg: str,
                                model: str = "claude",
                                max_tokens: int = 2048) -> str:
    """Call Claude via CLI subprocess (uses ANTHROPIC_API_KEY, charges API credits)."""
    import time

    if not CLAUDE_EXE:
        raise RuntimeError("Claude CLI가 설치되지 않았습니다 (CLAUDE_EXE not found)")

    full_prompt = (
        f"[역할 및 지시사항]\n{sys_prompt}\n\n"
        f"{'='*60}\n\n"
        f"[분석 자료 및 요청]\n{user_msg}"
    )

    env = os.environ.copy()

    for attempt in range(3):
        try:
            proc = subprocess.run(
                [CLAUDE_EXE, "--print"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        except subprocess.TimeoutExpired:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError("Claude CLI 응답 시간 초과 — 잠시 후 다시 시도해주세요") from None

        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()

        stderr = (proc.stderr or "").strip()[:300]
        if proc.returncode != 0:
            _err_log.error("Claude CLI exit %s: %s", proc.returncode, stderr)
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"Claude CLI 오류 (exit {proc.returncode}): {stderr}")

    raise RuntimeError("Claude CLI 응답 실패")



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


def _committee_phase1(sector: str, results: dict, call_fn=None, workspace_dir: Path = None) -> tuple:
    """Phase 1: 3 reviewers in parallel. Returns (reviews, scores, decisions, disagree, cfg)."""
    from concurrent.futures import ThreadPoolExecutor as _TPE
    call_fn = call_fn or _committee_call_gemini
    workspace_dir = workspace_dir or WORKSPACE_DIR

    research = f"# 연구 대상\n전문서비스 영역: **{sector}**\n\n"
    for key, info in QUERIES.items():
        if key in results:
            research += f"## {info['title']}\n\n{results[key]}\n\n---\n\n"

    cfg = json.loads(
        (BASE_DIR / "task2_neofirm" / "agents" / "reviewers.json").read_text(encoding="utf-8")
    )
    user_msg = f"## Research Material\n\n{research}"

    import time as _time
    def _timed_call(name, prompt):
        t = _time.time()
        res = call_fn(prompt, user_msg)
        _err_log.info(f"[Phase1/{name}] {_time.time()-t:.1f}s")
        return res

    t1_start = _time.time()
    with _TPE(max_workers=3) as pool:
        futs = {
            "market":     pool.submit(_timed_call, "market",     cfg["market_reviewer"]["prompt"]),
            "technology": pool.submit(_timed_call, "technology", cfg["technology_reviewer"]["prompt"]),
            "business":   pool.submit(_timed_call, "business",   cfg["business_reviewer"]["prompt"]),
        }
        reviews = {name: fut.result() for name, fut in futs.items()}
    _err_log.info(f"[Phase1/total-parallel] {_time.time()-t1_start:.1f}s")

    rev_dir = workspace_dir / "reviews"
    rev_dir.mkdir(parents=True, exist_ok=True)
    for name, text in reviews.items():
        (rev_dir / f"{name}_review.md").write_text(text, encoding="utf-8")

    scores    = {n: _committee_extract_score(t)    for n, t in reviews.items()}
    decisions = {n: _committee_extract_decision(t) for n, t in reviews.items()}

    disagree = []
    if len(set(decisions.values())) > 1:
        disagree.append({
            "id": "D00", "type": "decision",
            "issue": "Reviewers reached different final decisions",
            "reviewer_positions": decisions, "severity": "HIGH",
            "why_it_matters": "Split decision requires committee deliberation.",
        })

    comm_dir = workspace_dir / "committee"
    comm_dir.mkdir(exist_ok=True)
    (comm_dir / "disagreements.json").write_text(
        json.dumps({
            "decisions": decisions, "scores": scores,
            "disagreements": disagree,
            "needs_committee_discussion": bool(disagree),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return reviews, scores, decisions, disagree, cfg


def _committee_phase2(sector: str, reviews: dict, disagree: list, cfg: dict,
                       call_fn=None, workspace_dir: Path = None) -> tuple:
    """Phase 2: Committee discussion (only if disagreements). Returns (discussion, resolution)."""
    call_fn = call_fn or _committee_call_gemini
    workspace_dir = workspace_dir or WORKSPACE_DIR
    if not disagree:
        return "", ""

    comm_dir = workspace_dir / "committee"
    comm_dir.mkdir(exist_ok=True)

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
    discussion = call_fn(disc_sys, disc_user)
    (comm_dir / "discussion.md").write_text(discussion, encoding="utf-8")

    resolution = call_fn(
        "위원회 토론을 간략히 요약하고 이견 해소 결과를 정리하세요. 한국어, 마크다운.",
        discussion,
    )
    (comm_dir / "resolution.md").write_text(resolution, encoding="utf-8")

    return discussion, resolution


def _committee_phase3(sector: str, reviews: dict, discussion: str, cfg: dict,
                       call_fn=None, workspace_dir: Path = None) -> tuple:
    """Phase 3: Final decision memo. Returns (memo, final_decision)."""
    call_fn = call_fn or _committee_call_gemini
    workspace_dir = workspace_dir or WORKSPACE_DIR
    dec_user = (
        f"## Sector\n{sector}\n\n"
        f"## Market Review\n{reviews['market'][:1500]}\n\n"
        f"## Technology Review\n{reviews['technology'][:1500]}\n\n"
        f"## Business Review\n{reviews['business'][:1500]}\n\n"
        f"## Committee Discussion\n{discussion[:1000]}"
    )
    memo = call_fn(
        cfg["decision_maker"]["prompt"], dec_user,
        max_tokens=3000,
    )
    dec_dir = workspace_dir / "decision"
    dec_dir.mkdir(exist_ok=True)
    (dec_dir / "investment_memo.md").write_text(memo, encoding="utf-8")

    final_decision = _committee_extract_decision(memo)
    return memo, final_decision


def _committee_phase4(sector: str, results: dict, reviews: dict, scores: dict,
                       decisions: dict, final_decision: str, memo: str,
                       workspace_dir: Path = None) -> str:
    """Phase 4: Build slides_data.json and render committee PPTX. Returns pptx filename."""
    slides = []
    label_map = {"A": f"NeoFirm × {sector}", "B": "AI-전문가 작업 배분", "C": "1페이지 투자메모", "D": "문제정의문"}
    for key in ["A", "B", "C", "D"]:
        if key in results:
            slides.append({"title": label_map[key], "key_points": _committee_bullets(results[key]), "badge": ""})
    for rev_name, rev_title in [("market", "시장성 리뷰"), ("technology", "기술성 리뷰"), ("business", "사업성 리뷰")]:
        slides.append({"title": rev_title, "key_points": _committee_bullets(reviews[rev_name]), "badge": ""})
    slides.append({"title": f"최종 결정: {final_decision}", "key_points": _committee_bullets(memo), "badge": final_decision})

    slides_data = {
        "title": f"NeoFirm × {sector} 투자 분석",
        "sector": sector,
        "decision": final_decision,
        "scores_by_reviewer": scores,
        "decisions_by_reviewer": decisions,
        "slides": slides,
    }

    workspace_dir = workspace_dir or WORKSPACE_DIR
    pres_dir = workspace_dir / "presentation"
    pres_dir.mkdir(exist_ok=True)
    (pres_dir / "slides_data.json").write_text(
        json.dumps(slides_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

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

    # output/ 에도 복사하여 /api/download/{filename}으로 접근 가능하게
    import shutil as _sh
    output_copy = OUTPUT_DIR / pptx_path.name
    _sh.copy2(pptx_path, output_copy)
    _err_log.info(f"Committee PPTX copied to output: {output_copy}")

    return pptx_path.name


# ---------------------------------------------------------------------------
# Comparison report helper
# ---------------------------------------------------------------------------

def _generate_comparison_report(sector: str, gemini_data: dict, claude_data: dict) -> dict:
    """Compare Gemini and Claude committee results. Returns {report_md, comparison_json}."""
    comp_sys = (
        "당신은 두 AI 투자 위원회의 결과를 중립적으로 비교 분석하는 전문가입니다. "
        "근거의 질, 논리적 일관성, 위험 식별 능력을 기준으로 평가하세요. "
        "어느 모델이 더 정확하다고 가정하지 마세요. 한국어 마크다운으로 작성하세요."
    )
    comp_user = (
        f"## 분석 대상 섹터\n{sector}\n\n"
        f"## Gemini 위원회 결과\n"
        f"- 최종 판단: **{gemini_data.get('decision', 'N/A')}**\n"
        f"- 리뷰어 판단: {gemini_data.get('decisions_by_reviewer', {})}\n"
        f"- 투자 메모 (첫 1000자):\n{gemini_data.get('memo', '')[:1000]}\n\n"
        f"## Claude 위원회 결과\n"
        f"- 최종 판단: **{claude_data.get('decision', 'N/A')}**\n"
        f"- 리뷰어 판단: {claude_data.get('decisions_by_reviewer', {})}\n"
        f"- 투자 메모 (첫 1000자):\n{claude_data.get('memo', '')[:1000]}\n\n"
        f"## 비교 분석 요청\n"
        f"1. 투자 결정 비교 (일치/불일치, 이유)\n"
        f"2. 강세 논거 비교\n"
        f"3. 약세 논거 비교\n"
        f"4. 재무·리스크 분석 비교\n"
        f"5. 근거 품질 평가\n"
        f"6. 추론 방식의 차이점\n"
        f"7. 종합 결론"
    )
    report_md = _committee_call_gemini(comp_sys, comp_user, max_tokens=3000)

    comp_dir = OUTPUT_DIR / "comparison"
    comp_dir.mkdir(exist_ok=True)
    (comp_dir / "comparison_report.md").write_text(report_md, encoding="utf-8")

    comp_json = {
        "sector": sector,
        "gemini_decision": gemini_data.get("decision"),
        "claude_decision": claude_data.get("decision"),
        "decisions_agree": gemini_data.get("decision") == claude_data.get("decision"),
        "generated_at": datetime.now().isoformat(),
    }
    (comp_dir / "comparison.json").write_text(
        json.dumps(comp_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"report_md": report_md, "comparison": comp_json}


# ---------------------------------------------------------------------------
# Shared committee pipeline runner (used by both /generate-claude and /generate-both)
# ---------------------------------------------------------------------------

async def _run_committee_pipeline(sector: str, results: dict, call_fn, workspace_dir: Path,
                                   yield_fn, label: str = "") -> dict:
    """Run phases 1-4 and yield SSE events via yield_fn. Returns {decision, memo, pptx_filename}."""
    from functools import partial
    loop = asyncio.get_event_loop()

    p1 = partial(_committee_phase1, call_fn=call_fn, workspace_dir=workspace_dir)
    p2 = partial(_committee_phase2, call_fn=call_fn, workspace_dir=workspace_dir)
    p3 = partial(_committee_phase3, call_fn=call_fn, workspace_dir=workspace_dir)
    p4 = partial(_committee_phase4, workspace_dir=workspace_dir)

    prefix = f"{label}: " if label else ""

    await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 2, 'status': 'run', 'message': f'{prefix}시장·기술·사업 리뷰어 독립 평가 중…'}, ensure_ascii=False)}\n\n")
    reviews, scores, decisions, disagree, cfg = await loop.run_in_executor(_executor, p1, sector, results)
    await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 2, 'status': 'done', 'message': f'{prefix}리뷰어 평가 완료'}, ensure_ascii=False)}\n\n")
    await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 3, 'status': 'done', 'message': f'이견 {len(disagree)}건 감지'}, ensure_ascii=False)}\n\n")

    if disagree:
        await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 4, 'status': 'run', 'message': f'{prefix}AI 위원회 토론 진행 중…'}, ensure_ascii=False)}\n\n")
        discussion, resolution = await loop.run_in_executor(_executor, p2, sector, reviews, disagree, cfg)
        await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 4, 'status': 'done', 'message': f'{prefix}AI 토론 완료'}, ensure_ascii=False)}\n\n")
    else:
        discussion, resolution = "", ""
        await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 4, 'status': 'skip', 'message': '이견 없음 — 토론 생략'}, ensure_ascii=False)}\n\n")

    await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 5, 'status': 'run', 'message': f'{prefix}최종 투자 판단 작성 중…'}, ensure_ascii=False)}\n\n")
    memo, final_decision = await loop.run_in_executor(_executor, p3, sector, reviews, discussion, cfg)
    await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 5, 'status': 'done', 'message': f'{prefix}최종 판단: {final_decision}'}, ensure_ascii=False)}\n\n")

    await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 6, 'status': 'run', 'message': f'{prefix}PPT 생성 중…'}, ensure_ascii=False)}\n\n")
    pptx_filename = await loop.run_in_executor(_executor, p4, sector, results, reviews, scores, decisions, final_decision, memo)
    await yield_fn(f"data: {json.dumps({'type': 'committee_progress', 'wf_step': 6, 'status': 'done', 'message': f'{prefix}PPT 완료'}, ensure_ascii=False)}\n\n")

    return {
        "decision": final_decision,
        "memo": memo,
        "pptx_filename": pptx_filename,
        "decisions_by_reviewer": decisions,
        "scores_by_reviewer": scores,
    }


# ---------------------------------------------------------------------------
# Claude-only generate endpoint
# ---------------------------------------------------------------------------

@app.post("/api/generate-claude")
async def generate_claude(req: GenerateRequest):
    """Same as /api/generate but committee uses Claude Pro subscription CLI."""
    sector = req.sector.strip()
    if not sector:
        raise HTTPException(400, "전문서비스 영역을 입력해주세요")
    if not CLAUDE_EXE:
        raise HTTPException(503, "Claude 구독 CLI가 설치되지 않았습니다. API 과금으로 전환하지 않습니다")
    if platform.system() != "Windows" and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        raise HTTPException(503, "운영 Claude 구독 인증이 필요합니다")

    results: dict = {}
    events_queue: list = []

    async def _yld(ev: str):
        events_queue.append(ev)

    async def stream():
        for sub in ["reviews", "committee", "decision", "presentation", "research", "criteria", "logs"]:
            p = WORKSPACE_DIR_CLAUDE / sub
            if p.exists():
                import shutil as _ws_shutil
                _ws_shutil.rmtree(p, ignore_errors=True)
        WORKSPACE_DIR_CLAUDE.mkdir(parents=True, exist_ok=True)

        yield f"data: {json.dumps({'type': 'workspace_clear'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'start', 'sector': sector, 'engine': 'claude'}, ensure_ascii=False)}\n\n"

        # Research phase (shared: NLM / Gemini fallback)
        for key, info in QUERIES.items():
            yield f"data: {json.dumps({'type': 'progress', 'key': key, 'status': 'running'}, ensure_ascii=False)}\n\n"
            try:
                question = info["question"].format(sector=sector)
                answer = await run_nlm_query(question)
                results[key] = answer
                (OUTPUT_DIR / f"{key}_{info['step']}.md").write_text(
                    f"# {info['title']}\n\n**영역:** {sector}\n\n---\n\n{answer}", encoding="utf-8"
                )
                yield f"data: {json.dumps({'type': 'result', 'key': key, 'title': info['title'], 'content': answer}, ensure_ascii=False)}\n\n"
            except Exception as e:
                msg = str(e) or type(e).__name__
                _err_log.error(f"[{key}] {msg}\n{traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'error', 'key': key, 'message': msg}, ensure_ascii=False)}\n\n"

        if not results:
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            return

        # Research PPTX
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            pptx_path = await asyncio.get_event_loop().run_in_executor(_executor, _build_pptx, sector, results, ts)
            yield f"data: {json.dumps({'type': 'pptx', 'filename': pptx_path.name}, ensure_ascii=False)}\n\n"
        except Exception as e:
            _err_log.error(f"PPTX error: {e}")

        # Claude committee — asyncio.Queue for real-time event streaming
        yield f"data: {json.dumps({'type': 'committee_start', 'engine': 'claude'}, ensure_ascii=False)}\n\n"
        try:
            q: asyncio.Queue = asyncio.Queue()

            async def _yld_q(ev: str):
                await q.put(ev)

            pipeline_task = asyncio.ensure_future(
                _run_committee_pipeline(sector, results, _committee_call_claude_cli, WORKSPACE_DIR_CLAUDE, _yld_q, label="Claude")
            )
            _ka_t = asyncio.get_event_loop().time()
            while not pipeline_task.done():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=0.3)
                    yield ev
                    _ka_t = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    now = asyncio.get_event_loop().time()
                    if now - _ka_t >= 15:
                        yield ": keepalive\n\n"
                        _ka_t = now
            claude_result = await pipeline_task
            while not q.empty():
                yield await q.get()

            yield f"data: {json.dumps({'type': 'committee_done', 'engine': 'claude', 'decision': claude_result['decision'], 'pptx_filename': claude_result['pptx_filename'], 'memo_preview': claude_result['memo'][:300]}, ensure_ascii=False)}\n\n"
        except Exception as e:
            _err_log.error(f"Claude committee failed: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'committee_error', 'engine': 'claude', 'message': str(e)}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _with_run_status(stream()),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Both-engines comparison endpoint
# ---------------------------------------------------------------------------

@app.post("/api/generate-both")
async def generate_both(req: GenerateRequest):
    """Run Gemini + Claude committees on shared research, then produce comparison report."""
    sector = req.sector.strip()
    if not sector:
        raise HTTPException(400, "전문서비스 영역을 입력해주세요")
    if not CLAUDE_EXE:
        raise HTTPException(503, "Claude 구독 CLI가 설치되지 않았습니다. API 과금으로 전환하지 않습니다")
    if platform.system() != "Windows" and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        raise HTTPException(503, "운영 Claude 구독 인증이 필요합니다")

    results: dict = {}

    async def stream():
        # Clear both workspaces
        for ws in [WORKSPACE_DIR, WORKSPACE_DIR_CLAUDE]:
            for sub in ["reviews", "committee", "decision", "presentation", "research", "criteria", "logs"]:
                p = ws / sub
                if p.exists():
                    import shutil as _ws_shutil
                    _ws_shutil.rmtree(p, ignore_errors=True)
            ws.mkdir(parents=True, exist_ok=True)

        yield f"data: {json.dumps({'type': 'workspace_clear'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'start', 'sector': sector, 'engine': 'both'}, ensure_ascii=False)}\n\n"

        # Research phase
        for key, info in QUERIES.items():
            yield f"data: {json.dumps({'type': 'progress', 'key': key, 'status': 'running'}, ensure_ascii=False)}\n\n"
            try:
                question = info["question"].format(sector=sector)
                answer = await run_nlm_query(question)
                results[key] = answer
                (OUTPUT_DIR / f"{key}_{info['step']}.md").write_text(
                    f"# {info['title']}\n\n**영역:** {sector}\n\n---\n\n{answer}", encoding="utf-8"
                )
                yield f"data: {json.dumps({'type': 'result', 'key': key, 'title': info['title'], 'content': answer}, ensure_ascii=False)}\n\n"
            except Exception as e:
                msg = str(e) or type(e).__name__
                yield f"data: {json.dumps({'type': 'error', 'key': key, 'message': msg}, ensure_ascii=False)}\n\n"

        if not results:
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            return

        # Research PPTX
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            pptx_path = await asyncio.get_event_loop().run_in_executor(_executor, _build_pptx, sector, results, ts)
            yield f"data: {json.dumps({'type': 'pptx', 'filename': pptx_path.name}, ensure_ascii=False)}\n\n"
        except Exception as e:
            _err_log.error(f"PPTX error: {e}")

        gemini_result = None
        claude_result = None

        # ── Gemini committee — real-time streaming via Queue ────────
        yield f"data: {json.dumps({'type': 'committee_start', 'engine': 'gemini'}, ensure_ascii=False)}\n\n"
        try:
            q_g: asyncio.Queue = asyncio.Queue()
            async def _yld_g(ev): await q_g.put(ev)
            task_g = asyncio.ensure_future(
                _run_committee_pipeline(sector, results, _committee_call_gemini, WORKSPACE_DIR, _yld_g, label="Gemini")
            )
            _ka_g = asyncio.get_event_loop().time()
            while not task_g.done():
                try:
                    ev_g = await asyncio.wait_for(q_g.get(), timeout=0.3)
                    yield ev_g
                    _ka_g = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    now = asyncio.get_event_loop().time()
                    if now - _ka_g >= 15:
                        yield ": keepalive\n\n"
                        _ka_g = now
            gemini_result = await task_g
            while not q_g.empty():
                yield await q_g.get()
            yield f"data: {json.dumps({'type': 'committee_done', 'engine': 'gemini', 'decision': gemini_result['decision'], 'pptx_filename': gemini_result['pptx_filename'], 'memo_preview': gemini_result['memo'][:300]}, ensure_ascii=False)}\n\n"
        except Exception as e:
            _err_log.error(f"Gemini committee failed: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'committee_error', 'engine': 'gemini', 'message': str(e)}, ensure_ascii=False)}\n\n"

        # ── Claude committee — real-time streaming via Queue ─────────
        yield f"data: {json.dumps({'type': 'committee_start', 'engine': 'claude'}, ensure_ascii=False)}\n\n"
        try:
            q_c: asyncio.Queue = asyncio.Queue()
            async def _yld_c(ev): await q_c.put(ev)
            task_c = asyncio.ensure_future(
                _run_committee_pipeline(sector, results, _committee_call_claude_cli, WORKSPACE_DIR_CLAUDE, _yld_c, label="Claude")
            )
            _ka_c = asyncio.get_event_loop().time()
            while not task_c.done():
                try:
                    ev_c = await asyncio.wait_for(q_c.get(), timeout=0.3)
                    yield ev_c
                    _ka_c = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    now = asyncio.get_event_loop().time()
                    if now - _ka_c >= 15:
                        yield ": keepalive\n\n"
                        _ka_c = now
            claude_result = await task_c
            while not q_c.empty():
                yield await q_c.get()
            yield f"data: {json.dumps({'type': 'committee_done', 'engine': 'claude', 'decision': claude_result['decision'], 'pptx_filename': claude_result['pptx_filename'], 'memo_preview': claude_result['memo'][:300]}, ensure_ascii=False)}\n\n"
        except Exception as e:
            _err_log.error(f"Claude committee failed: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'committee_error', 'engine': 'claude', 'message': str(e)}, ensure_ascii=False)}\n\n"

        # ── Comparison ──────────────────────────────────────────────
        if gemini_result and claude_result:
            yield f"data: {json.dumps({'type': 'comparison_start'}, ensure_ascii=False)}\n\n"
            try:
                loop = asyncio.get_event_loop()
                comp = await loop.run_in_executor(
                    _executor, _generate_comparison_report, sector, gemini_result, claude_result
                )
                yield f"data: {json.dumps({'type': 'comparison_done', 'gemini_decision': comp['comparison']['gemini_decision'], 'claude_decision': comp['comparison']['claude_decision'], 'decisions_agree': comp['comparison']['decisions_agree']}, ensure_ascii=False)}\n\n"
            except Exception as e:
                _err_log.error(f"Comparison failed: {e}")
                yield f"data: {json.dumps({'type': 'comparison_error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _with_run_status(stream(), expected_committees=2, require_comparison=True),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/comparison")
async def get_comparison():
    """Return the latest comparison report and JSON."""
    comp_dir = OUTPUT_DIR / "comparison"
    report = ""
    comp_json = {}
    if (comp_dir / "comparison_report.md").exists():
        report = (comp_dir / "comparison_report.md").read_text(encoding="utf-8")
    if (comp_dir / "comparison.json").exists():
        try:
            comp_json = json.loads((comp_dir / "comparison.json").read_text(encoding="utf-8"))
        except Exception:
            pass

    # Claude workspace PPTX
    claude_pptx = None
    pptx_dir = WORKSPACE_DIR_CLAUDE / "presentation"
    if pptx_dir.exists():
        pptxs = sorted(pptx_dir.glob("*.pptx"), key=lambda f: f.stat().st_mtime, reverse=True)
        if pptxs:
            claude_pptx = pptxs[0].name

    return {"report": report, "comparison": comp_json, "claude_pptx": claude_pptx}


@app.get("/api/workspace-claude/download")
async def workspace_claude_download():
    """Download the latest Claude committee PPTX."""
    pptx_dir = WORKSPACE_DIR_CLAUDE / "presentation"
    if not pptx_dir.exists():
        raise HTTPException(404, "Claude PPTX 없음")
    pptxs = sorted(pptx_dir.glob("*.pptx"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not pptxs:
        raise HTTPException(404, "PPTX 파일 없음")
    return FileResponse(
        pptxs[0],
        filename="neofirm_claude_report.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


def _read_workspace(ws_dir: Path) -> dict:
    """Read workspace artifacts from the given directory and return as dict."""
    def read(rel: str) -> str:
        p = ws_dir / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    pptx_file = None
    pptx_dir = ws_dir / "presentation"
    if pptx_dir.exists():
        pptxs = sorted(pptx_dir.glob("*.pptx"), key=lambda f: f.stat().st_mtime, reverse=True)
        if pptxs:
            pptx_file = pptxs[0].name

    disagreements_raw = read("committee/disagreements.json")
    try:
        disagreements = json.loads(disagreements_raw) if disagreements_raw else {}
    except Exception:
        disagreements = {}

    sector = ""
    slides_decision = ""
    slides_json_path = ws_dir / "presentation" / "slides_data.json"
    if slides_json_path.exists():
        try:
            slides_data = json.loads(slides_json_path.read_text(encoding="utf-8"))
            sector = slides_data.get("sector", "")
            slides_decision = slides_data.get("decision", "")
        except Exception:
            pass

    return {
        "sector": sector,
        "slides_decision": slides_decision,
        "reviews": {
            "market":     read("reviews/market_review.md"),
            "technology": read("reviews/technology_review.md"),
            "business":   read("reviews/business_review.md"),
        },
        "disagreements":        disagreements,
        "committee_discussion": read("committee/discussion.md"),
        "resolution":           read("committee/resolution.md"),
        "investment_memo":      read("decision/investment_memo.md"),
        "pptx_filename":        pptx_file,
    }


@app.get("/api/workspace")
async def workspace():
    """Return all Task 2 pipeline artifacts as JSON (Gemini workspace)."""
    return _read_workspace(WORKSPACE_DIR)


@app.get("/api/workspace-claude/data")
async def workspace_claude_data():
    """Return all Task 2 pipeline artifacts as JSON (Claude workspace)."""
    return _read_workspace(WORKSPACE_DIR_CLAUDE)


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
    if not path.is_relative_to(OUTPUT_DIR.resolve()):
        raise HTTPException(400, "잘못된 경로입니다")
    if not path.is_file():
        raise HTTPException(404, "파일이 없습니다. 먼저 생성을 실행해주세요.")
    media = "application/vnd.openxmlformats-officedocument.presentationml.presentation" if filename.endswith(".pptx") else "text/markdown; charset=utf-8"
    return FileResponse(
        path,
        filename=path.name,
        media_type=media,
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

    import re as _re

    def _extract_bullets(text: str, n: int = 7) -> list:
        out = []
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or "|" in line or line.startswith("---"):
                continue
            line = _re.sub(r"^[-•*▸]\s*", "", line).strip()
            line = _re.sub(r"^\d+\.\s*", "", line).strip()
            line = _re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            line = _re.sub(r"\[(\d+(?:,\s*\d+)*)\]", "", line).strip()
            if len(line) > 8:
                out.append(line[:110] + ("…" if len(line) > 110 else ""))
            if len(out) >= n:
                break
        return out

    def _pptx_title_from_content(sector: str, results: dict) -> str:
        d_text = results.get("D", "")
        for line in d_text.splitlines():
            line = _re.sub(r"[#*`|>_~\[\]]+", "", line).strip()
            line = _re.sub(r"\s+", " ", line)
            if 15 < len(line) < 65 and not line.startswith("※") and not line.startswith("추가"):
                return line
        return f"{sector} 전문서비스 혁신 분석"

    LIGHT_GRAY = RGBColor(0xF4, 0xF5, 0xF7)
    TEXT_DARK  = RGBColor(0x1a, 0x1a, 0x2e)
    TEXT_MID   = RGBColor(0x55, 0x60, 0x75)

    report_title = _pptx_title_from_content(sector, results)

    # ── Slide 1: Title ──────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank_layout)
    _add_rect(slide, 0, 0, 13.33, 7.5, NAVY)
    _add_rect(slide, 0, 5.8, 13.33, 1.7, ACCENT)
    _add_textbox(slide, "NeoFirm", 1, 1.0, 11.33, 0.9, 42, True, WHITE, align=PP_ALIGN.CENTER)
    _add_textbox(slide, report_title, 1, 2.1, 11.33, 1.1, 24, True, WHITE, align=PP_ALIGN.CENTER)
    _add_textbox(slide, sector, 1, 3.4, 11.33, 0.7, 18, False, ACCENT, align=PP_ALIGN.CENTER)
    _add_textbox(slide, f"생성일시: {ts}  |  AI 분석 시스템", 1, 6.0, 11.33, 0.6, 13, False, WHITE, align=PP_ALIGN.CENTER)

    # ── Content slides ──────────────────────────────────────────────────
    for key, info in QUERIES.items():
        if key not in results:
            continue
        slide = prs.slides.add_slide(blank_layout)

        # 상단 헤더 바
        _add_rect(slide, 0, 0, 13.33, 1.15, NAVY)
        # 섹션 레이블 (우측 상단)
        _add_textbox(slide, f"과제 {key}", 11.0, 0.18, 2.0, 0.55, 13, False, ACCENT, align=PP_ALIGN.RIGHT)
        _add_textbox(slide, info["title"], 0.4, 0.18, 10.5, 0.75, 20, True, WHITE)

        # 불릿 포인트 추출
        bullets = _extract_bullets(results[key], n=7)
        y = 1.35
        for i, pt in enumerate(bullets):
            dot_color = ACCENT if i == 0 else TEXT_MID
            _add_textbox(slide, "▸", 0.4, y, 0.35, 0.52, 13, True, dot_color)
            _add_textbox(slide, pt, 0.75, y, 12.0, 0.52, 13, False, TEXT_DARK)
            y += 0.54

        # 하단 회색 구분선
        _add_rect(slide, 0.4, 7.1, 12.53, 0.03, RGBColor(0xCC, 0xD0, 0xDC))

    # ── Slide: Summary ──────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank_layout)
    _add_rect(slide, 0, 0, 13.33, 1.15, NAVY)
    _add_textbox(slide, "전체 요약 · Next Steps", 0.4, 0.18, 10.5, 0.75, 20, True, WHITE)

    key_labels = {"A": "가치사슬 해부", "B": "AI-전문가 작업 배분", "C": "1페이지 투자메모", "D": "문제정의문"}
    y = 1.4
    for key in ["A", "B", "C", "D"]:
        if key in results:
            bullets = _extract_bullets(results[key], n=1)
            snippet = bullets[0] if bullets else "—"
            _add_textbox(slide, f"{key}.", 0.4, y, 0.5, 0.55, 14, True, ACCENT)
            _add_textbox(slide, f"{key_labels[key]}  —  {snippet}", 0.9, y, 11.8, 0.55, 13, False, TEXT_DARK)
        else:
            _add_textbox(slide, f"{key}.", 0.4, y, 0.5, 0.55, 14, True, TEXT_MID)
            _add_textbox(slide, f"{key_labels[key]}  —  생성 실패", 0.9, y, 11.8, 0.55, 13, False, TEXT_MID)
        y += 0.60

    _add_rect(slide, 0.4, y + 0.1, 12.53, 0.03, RGBColor(0xCC, 0xD0, 0xDC))
    _add_textbox(slide, f"Next: {sector} 프로토타입 설계  →  MVP 개발  →  초기 고객 검증",
                 0.4, y + 0.25, 12.53, 0.6, 14, False, ACCENT)

    safe_sector = "".join(c if c.isalnum() or c in "-_ " else "_" for c in sector)[:30]
    fname = f"NeoFirm_{safe_sector}_{datetime.now().strftime('%Y%m%d_%H%M')}.pptx"
    out_path = OUTPUT_DIR / fname
    prs.save(str(out_path))
    return out_path
