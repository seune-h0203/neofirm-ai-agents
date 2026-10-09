# NeoFirm Task 2 — Requirements

**GCS 9기 과제 #6 Task 2**  
**마감:** 2026-10-13 09:00

---

## 실행 환경

| 도구 | 역할 |
|------|------|
| **Claude Code CLI** | AI 에이전트 실행 (debate, synthesis, slides, review) |
| **NotebookLM CLI** | 리서치 / 소스 기반 분석 |
| **Python** | 오케스트레이션 |
| **python-pptx** | PPTX 최종 생성 |

> **주의:** Task 2는 Claude Code CLI 로컬 인증 세션을 사용합니다.  
> `ANTHROPIC_API_KEY` **불필요**. Anthropic Python SDK 직접 호출 **없음**.  
> Task 1.1 / 1.2는 Codex 기반이며 이 파일의 범위가 아닙니다.

---

## 파이프라인 전체 흐름

```
NotebookLM CLI (리서치)
        ↓
Claude Code CLI — Market Agent   ┐
Claude Code CLI — Execution Agent ├─ Round 1 독립 포지션 (병렬)
Claude Code CLI — Skeptic Agent  ┘
        ↓
Claude Code CLI — Market Agent   ┐
Claude Code CLI — Execution Agent ├─ Round 2 반박 (병렬)
Claude Code CLI — Skeptic Agent  ┘
        ↓
Claude Code CLI — Market Agent   ┐
Claude Code CLI — Execution Agent ├─ Round 3 최종 입장 (병렬)
Claude Code CLI — Skeptic Agent  ┘
        ↓
Claude Code CLI — Final Synthesis Agent
        ↓
Claude Code CLI — Slide JSON Generation
        ↓
Claude Code CLI — Independent Quality Review
        ↓  (fail → revision → review again, 최대 3회)
python-pptx — PPTX Rendering
```

---

## 파일 구조

```
neofirm/
├── scripts/
│   ├── run_neofirm.py      ← 메인 오케스트레이터
│   └── render_neofirm.py   ← PPTX 렌더러
├── tests/
│   └── test_neofirm.py     ← 단위 테스트
├── runs/
│   └── <run-id>/           ← 실행 증빙 (자동 생성)
│       ├── research.md
│       ├── debate.md
│       ├── synthesis.md
│       ├── slides.json
│       ├── review.json
│       ├── manifest.json
│       ├── evidence/       ← 에이전트별 호출 증빙 JSON
│       └── NeoFirm_*.pptx
└── output/                 ← 최종 PPTX 복사본
```

---

## 에이전트 역할

### Market Agent
- 관점: 시장/고객 관점
- 담당: 고객 페인포인트, 시장 규모, 지불 의사, 경쟁 환경, GTM

### Execution Agent
- 관점: 기술/실행 가능성 관점
- 담당: 기술 스택, AI 역량, 프로세스 자동화, 인재, 확장성, 운영 리스크

### Skeptic Agent
- 관점: 비판/리스크 관점
- 담당: 미검증 가정, 규제 리스크, 품질 리스크, 경쟁 위협, 실패 시나리오

---

## 토론 구조

| 라운드 | 내용 |
|--------|------|
| Round 1 | 각 에이전트 독립적 포지션 제시 |
| Round 2 | 다른 에이전트 포지션 읽고 반박 |
| Round 3 | 반박 수용 후 [유지/수정/철회] 최종 입장 |
| Synthesis | 별도 합성 에이전트가 전체 결론 도출 |

---

## 실행 방법

```powershell
cd C:\Users\elice\neofirm
python scripts/run_neofirm.py "IT/소프트웨어"
```

---

## 테스트

```powershell
cd C:\Users\elice\neofirm
python -m pytest tests/test_neofirm.py -v
```

---

## 완료 기준

- [ ] `claude --version` 또는 `npx @anthropic-ai/claude-code --version` 확인
- [ ] 3개 에이전트 × 3라운드 = 9회 독립 Claude CLI 호출
- [ ] 합성, 슬라이드 생성, 품질 검토 각 1회 이상 Claude CLI 호출
- [ ] `runs/<run-id>/debate.md` 에 Round 1/2/3 모두 기록
- [ ] PPTX 파일 생성 및 정상 열림 확인
- [ ] 단위 테스트 전체 PASS
- [ ] `ANTHROPIC_API_KEY` 환경변수 없이 실행 가능
