"""
NeoFirm 과제 자동 생성기
사용법: python generate.py "전문서비스 영역"
예시:  python generate.py "노무 (근로계약·급여)"
"""

import subprocess
import sys
import json
import os
from datetime import datetime
from pathlib import Path

NOTEBOOK_ID = "61af6e10-ae3a-4e54-8da5-41302feebcef"
OUTPUT_DIR = Path(__file__).parent / "output"
import shutil as _shutil
import sys as _sys
from pathlib import Path as _Path

def _find_nlm() -> str:
    found = _shutil.which("nlm")
    if found:
        return found
    scripts = _Path(_sys.executable).parent / "Scripts" / "nlm.exe"
    if scripts.exists():
        return str(scripts)
    return "nlm"

NLM = _find_nlm()

QUERIES = {
    "A_가치사슬": """\
전문서비스 영역: {sector}

위 영역을 기준으로 NeoFirm 과제 A (기존 가치사슬 해부)를 작성해줘.
반드시 아래 4가지 항목을 각각 구체적으로 답해줘:
1. 고객은 누구에게 어떤 결과를 사는가?
2. 현재 업무 단계와 각 단계별 담당자·소요시간·오류율은?
3. 공급자의 매출이 시간·인원과 어떻게 연결되는가?
4. 고객이 가장 싫어하는 대기, 재작업, 불확실성은 어디에서 생기는가?
한국어로, 표나 bullet 형식으로 정리해줘.\
""",

    "B_작업배분": """\
전문서비스 영역: {sector}

위 영역을 기준으로 NeoFirm 과제 B (AI-전문가 작업 배분표)를 작성해줘.
아래 4가지 구분으로 표를 만들어줘:
- 자동화: 규칙이 명확하고 검증 가능한 반복작업
- 보조(AI초안+전문가검증): AI가 초안을 내되 전문가가 쉽게 검증 가능한 작업
- 전문가 전담: 모호성·이해상충·고위험 판단
- 금지: 책임주체 불명확하거나 검증 불가능한 작업
각 구분마다 구체적인 업무 예시를 3개 이상 포함해줘. 한국어 표 형식.\
""",

    "C_투자메모": """\
전문서비스 영역: {sector}

위 영역을 기준으로 NeoFirm 과제 C (1페이지 투자메모)를 작성해줘.
반드시 아래 7개 항목을 모두 포함해줘:
1. 시장 규모 및 고객의 현재 지출 (한국 시장 기준 추정)
2. 첫 번째로 표준화할 좁은 업무 (구체적인 서비스 단위)
3. 결과 단위와 가격 구조 (건당 고정가 또는 성과가 예시)
4. 전문가 개입률 목표와 품질 지표
5. 책임·보험·규제 구조 (오류 시 책임 소재, 관련 법령)
6. 100건 수행 후 쌓이는 독점 데이터 (어떤 데이터가 해자가 되는가)
7. SaaS 판매보다 직접 서비스를 선택해야 하는 이유
한국어로, 각 항목을 명확히 구분해서 작성해줘.\
""",

    "D_문제정의문": """\
전문서비스 영역: {sector}

위 영역을 기준으로 NeoFirm 문제정의문을 작성해줘.
아래 템플릿을 채워서 완성된 문제정의문을 만들어줘:

[고객]은 [전문서비스 결과]를 얻기 위해 [시간·비용·불확실성]을 감수하고 있다.
기존 공급자는 [시간당 과금·수작업·파편화] 때문에 개선할 유인이 약하다.
우리는 [AI 정상경로 처리]와 [전문가 예외판단]을 결합해 [측정 가능한 결과]를
[고정가·성과가]로 제공하고, [업무 피드백]을 축적해 매 건 더 빠르고 정확해지는
서비스를 만든다.

템플릿의 [ ] 부분을 구체적인 내용으로 채워서 완성된 한 단락 문장으로 작성해줘.
추가로 아래도 작성해줘:
- 타깃 고객 프로필 (1-2줄)
- 핵심 가치제안 (1-2줄)
- 첫 번째 KPI 3가지\
""",
}


def run_query(question: str, conversation_id: str | None = None) -> tuple[str, str]:
    if not NLM or NLM == "nlm":
        # NLM == "nlm" means fallback string, may not exist
        import shutil as _sh
        if not _sh.which(NLM or "nlm"):
            raise RuntimeError(
                f"nlm executable not found. "
                f"Searched PATH and {_Path(_sys.executable).parent / 'Scripts' / 'nlm.exe'}"
            )

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    scripts_dir = str(_Path(_sys.executable).parent / "Scripts")
    env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")

    cmd = [NLM, "notebook", "query", NOTEBOOK_ID, question]
    if conversation_id:
        cmd += ["--conversation-id", conversation_id]

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=180,
    )
    if result.returncode != 0:
        # Rich console prints errors to stdout, not stderr
        msg = result.stdout.strip() or result.stderr.strip() or f"nlm exited with code {result.returncode}"
        raise RuntimeError(f"nlm 오류 (rc={result.returncode}): {msg}")

    # stdout: answer text + optional Sources: + Conversation ID: sections
    answer = result.stdout.strip()
    extracted_conv_id = ""

    # Extract conversation_id from footer if present
    for line in result.stdout.splitlines():
        if line.startswith("Conversation ID:"):
            extracted_conv_id = line.split(":", 1)[1].strip()

    # Strip trailing sections
    for sep in ("\nSources:", "\n\nSources:", "\nConversation ID:", "\n\nConversation ID:"):
        idx = answer.find(sep)
        if idx != -1:
            answer = answer[:idx].strip()
            break

    return answer, extracted_conv_id


def save_output(filename: str, title: str, sector: str, content: str):
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"**전문서비스 영역:** {sector}\n\n")
        f.write(f"**생성일시:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("---\n\n")
        f.write(content)
    print(f"  저장: {path}")
    return path


def main():
    if len(sys.argv) < 2:
        print("사용법: python generate.py \"전문서비스 영역\"")
        print("예시:  python generate.py \"노무 (근로계약·급여)\"")
        sys.exit(1)

    sector = sys.argv[1]
    print(f"\n=== NeoFirm 과제 자동 생성 ===")
    print(f"전문서비스 영역: {sector}")
    print(f"노트북 ID: {NOTEBOOK_ID}\n")

    results = {}
    conv_id = None

    for key, query_template in QUERIES.items():
        label = key.split("_")[1]
        print(f"[{key}] {label} 생성 중...")

        question = query_template.format(sector=sector)
        try:
            answer, conv_id = run_query(question, conv_id if key != "A_가치사슬" else None)
            filename = f"{key}.md"
            title_map = {
                "A_가치사슬": "과제 A: 기존 가치사슬 해부 분석서",
                "B_작업배분": "과제 B: AI-전문가 작업 배분표",
                "C_투자메모": "과제 C: 1페이지 투자메모",
                "D_문제정의문": "문제정의문",
            }
            path = save_output(filename, title_map[key], sector, answer)
            results[key] = str(path)
            print(f"  완료\n")
        except Exception as e:
            print(f"  오류: {e}\n")
            results[key] = f"오류: {e}"

    # 통합 보고서 생성
    print("[통합] 전체 보고서 합치는 중...")
    report_path = OUTPUT_DIR / "NeoFirm_과제_전체.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# NeoFirm 과제 전체 보고서\n\n")
        f.write(f"**전문서비스 영역:** {sector}\n\n")
        f.write(f"**생성일시:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("---\n\n")
        for key, path in results.items():
            if not path.startswith("오류"):
                with open(path, encoding="utf-8") as part:
                    f.write(part.read())
                    f.write("\n\n---\n\n")

    print(f"\n=== 완료 ===")
    print(f"통합 보고서: {report_path}")
    print(f"개별 파일: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
