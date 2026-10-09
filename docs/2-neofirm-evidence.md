# NeoFirm Task 2 — Evidence Template

**파이프라인:** Claude Code CLI + NotebookLM CLI  
**실행일:** (실행 후 자동 채워짐)

---

## 실행 증빙 체크리스트

### 1. Claude Code CLI 인증

```
Claude Code version: (npx @anthropic-ai/claude-code --version 결과)
인증 방식: 로컬 OAuth 세션 (ANTHROPIC_API_KEY 불필요)
```

### 2. NotebookLM 리서치

| 섹션 | 파일 | 상태 |
|------|------|------|
| 가치사슬 | `runs/<id>/research.md` | |
| 작업배분 | `runs/<id>/research.md` | |
| 투자메모 | `runs/<id>/research.md` | |
| 문제정의 | `runs/<id>/research.md` | |

### 3. Agent Debate

| 에이전트 | Round 1 | Round 2 | Round 3 |
|----------|---------|---------|---------|
| Market | | | |
| Execution | | | |
| Skeptic | | | |

증빙 파일: `runs/<id>/debate.md`

### 4. Synthesis + Slides + Review

| 단계 | 증빙 파일 | 상태 |
|------|---------|------|
| Final Synthesis | `runs/<id>/synthesis.md` | |
| Slide JSON | `runs/<id>/slides.json` | |
| Quality Review | `runs/<id>/review.json` | |
| PPTX | `runs/<id>/NeoFirm_*.pptx` | |

### 5. Claude CLI 호출 로그

`runs/<id>/evidence/` 디렉토리에 에이전트별 JSON 파일:

```
evidence/
├── <timestamp>_research_value_chain.json    ← NLM fallback (있을 경우)
├── <timestamp>_round1_market.json
├── <timestamp>_round1_execution.json
├── <timestamp>_round1_skeptic.json
├── <timestamp>_round2_market.json
├── <timestamp>_round2_execution.json
├── <timestamp>_round2_skeptic.json
├── <timestamp>_round3_market.json
├── <timestamp>_round3_execution.json
├── <timestamp>_round3_skeptic.json
├── <timestamp>_synthesis.json
├── <timestamp>_slide_generation.json
└── <timestamp>_quality_review.json
```

각 파일 형식:
```json
{
  "label": "round1_market",
  "timestamp": "20261009_...",
  "claude_cmd": "npx",
  "elapsed_s": 12.3,
  "prompt_length": 842,
  "system_role_length": 245,
  "response_length": 1204,
  "response_preview": "..."
}
```

---

## 검증 기준

- **PASS:** 모든 evidence JSON 파일 존재 + debate.md에 3라운드 모두 기록 + PPTX 정상 생성
- **PARTIAL:** 일부 에이전트/라운드 누락 또는 NLM fallback으로 실행
- **FAIL:** Claude CLI 인증 실패 또는 파이프라인 중단

---

## 실제 실행 결과 (실행 후 채워야 함)

```
실행 명령어:
  python scripts/run_neofirm.py "IT/소프트웨어"

Run ID:
  <자동 생성된 run-id>

실행 시간:
  <분>분 <초>초

에이전트 호출 횟수:
  총 <n>회

PPTX 경로:
  runs/<id>/NeoFirm_IT_소프트웨어_<timestamp>.pptx

Quality Review:
  PASS / FAIL
```
