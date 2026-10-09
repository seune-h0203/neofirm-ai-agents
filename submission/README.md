# GCS 9기 과제 #6 — 제출물

**제출자:** elice0105412@gmail.com  
**작성일:** 2026-10-08  
**서버:** NeoFirm Generator (`localhost:8000`)

---

## 제출물 구조

```
submission/
├── README.md                        ← 이 파일
├── 과제1.1/
│   └── gcs_pulse_comparison.md      ← MCP vs CLI 비교 보고서
├── 과제1.2/
│   ├── skills/room-booking/         ← Codex Custom Skill 전체 소스
│   │   ├── SKILL.md                 ← 사용법·API 문서
│   │   ├── skill.yaml               ← Codex manifest
│   │   ├── book_room_event.py       ← CLI 진입점
│   │   ├── requirements.txt
│   │   ├── gcs_pulse/               ← GCS-PULSE HTTP/Mock 클라이언트
│   │   └── gws/                     ← Google Calendar 클라이언트
│   └── test_results/                ← dry-run 테스트 로그 4종
└── 과제2/
    ├── app.py                       ← NeoFirm 자동화 서버
    ├── output/
    │   ├── A_가치사슬.md
    │   ├── B_작업배분.md
    │   ├── C_투자메모.md
    │   ├── D_문제정의.md
    │   ├── 전체보고서.md
    │   └── NeoFirm_발표자료.pptx    ← 자동 생성 발표자료
    └── logs/
        └── generation_error.log
```

---

## 실행 방법

### 서버 시작

```powershell
cd C:\Users\elice\neofirm
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

브라우저에서 `http://localhost:8000` 접속 → 영역 입력 → 생성 버튼

### room-booking Skill (dry-run)

```powershell
cd C:\Users\elice\neofirm\skills\room-booking
python book_room_event.py `
  --title "Q4 Planning" `
  --start "2026-10-15T10:00:00+09:00" `
  --end   "2026-10-15T12:00:00+09:00" `
  --attendees 이메일@example.com `
  --room-preference "large" `
  --dry-run --json
```

---

## 필요한 환경변수

| 변수 | 과제 | 설명 |
|------|------|------|
| `GCS_PULSE_API_URL` | 1.2 | `https://api.1000.school` (프론트 app.1000.school 아님; 미설정 시 mock) |
| `GCS_PULSE_API_KEY` | 1.2 | GCS-PULSE Bearer 키 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 1.2 | GCP 서비스 계정 JSON 경로 |
| `GOOGLE_CALENDAR_ID` | 1.2 | 대상 캘린더 ID (기본: `primary`) |

> **보안 주의:** API 키, OAuth 토큰, 쿠키 등 인증정보는 이 제출물에 포함되지 않습니다.

---

## 테스트 결과 요약

### 과제 1.1

| 항목 | 상태 |
|------|------|
| MCP vs CLI 비교 보고서 | ✅ 완료 |
| 토큰 사용량 | 추정치 (방법론 기반, 실측 불가) |
| 비교 기준 | 단일 조작 및 세션 단위 토큰 수 |

### 과제 1.2

| 항목 | 상태 |
|------|------|
| Skill 구조 구현 | ✅ 완료 |
| Mock dry-run 4시나리오 | ✅ 모두 `dry_run_ok` |
| 실제 GCS-PULSE 연결 | ✅ `api.1000.school` 라이브 dry-run 성공 (회의실 14개, 예약현황 조회) |
| Google Calendar 연결 | 🔄 서비스 계정 설정 시 활성화 |
| 이메일 발송 | 🔄 Calendar API (`sendUpdates: "all"`) 연동 시 자동 발송 |
| 오류·롤백 처리 | ✅ 구현 완료 |

### 과제 2

| 항목 | 상태 |
|------|------|
| NeoFirm 서버 | ✅ `localhost:8000` 정상 동작 |
| NotebookLM CLI 연동 | ✅ `nlm.exe` 탐지·실행 확인 |
| SSE 4섹션 생성 | ✅ 구현 완료 (이전 실행 결과 `output/` 저장) |
| PPTX 자동 생성 | ✅ 생성 완료 (`NeoFirm_발표자료.pptx`, 39KB) |
| 단일 명령 실행 | ✅ `POST /api/generate` 한 번으로 전체 파이프라인 실행 |

---

## 미해결 문제

1. **GCS-PULSE 실제 예약 (외부 상태 변경):** dry-run 성공 확인 완료. `--dry-run` 제거 후 실행 시 실제 예약 생성. 실행 전 사용자 확인 필요.

2. **Google Calendar 실제 등록:** `GOOGLE_SERVICE_ACCOUNT_JSON` 경로 및 서비스 계정 권한 설정 필요.

3. **NotebookLM 컨텍스트:** 현재 Notebook에 등록된 소스 문서에 NeoFirm 과제별 세부 기준이 없어 "소스 없음" 응답이 반환됨. 과제 가이드 PDF를 Notebook에 업로드하면 정확한 답변 생성 가능.

---

## 실행 증빙

- `submission/과제1.2/test_results/` — 4개 dry-run 테스트 로그
- `submission/과제2/output/` — 생성된 .md 파일 및 .pptx
- `submission/과제2/logs/generation_error.log` — 서버 실행 로그
