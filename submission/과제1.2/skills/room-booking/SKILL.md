# book-room-event

**Version:** 1.0.0  
**Entry point:** `book_room_event.py`  
**On error:** rollback

## 개요

GCS-PULSE CLI와 GWS Calendar API를 단일 자연어 요청으로 연결하는 Codex Custom Skill.

```
사용자 요청
→ GCS-PULSE: 회의실 목록 조회
→ GCS-PULSE: 예약 가능 여부 확인 (대안 fallback 포함)
→ GCS-PULSE: 회의실 예약
→ GWS Calendar: 일정 생성 + 팀원 초대
→ 초대 이메일 자동 발송 (sendUpdates: "all")
→ SkillResult 반환
```

## 파일 구조

```
skills/room-booking/
├── SKILL.md              # 이 파일
├── skill.yaml            # Codex manifest
├── book_room_event.py    # 진입점 (CLI + Python API)
├── requirements.txt      # 의존성
├── gcs_pulse/
│   ├── __init__.py
│   ├── client.py         # GCS-PULSE HTTP/Mock 클라이언트
│   └── models.py         # Room, Booking 데이터클래스
└── gws/
    ├── __init__.py
    └── calendar.py       # Google Calendar API 클라이언트
```

## 실행 방법

### CLI (dry-run — 외부 상태 변경 없음)

```bash
cd skills/room-booking
python book_room_event.py \
  --title "Q4 Planning" \
  --start "2026-10-15T10:00:00+09:00" \
  --end   "2026-10-15T12:00:00+09:00" \
  --attendees alice@example.com bob@example.com \
  --room-preference "large" \
  --location "Seoul HQ" \
  --dry-run --json
```

### 실제 예약 (외부 상태 변경 — 실행 전 확인 필요)

```bash
export GCS_PULSE_API_URL=https://app.1000.school
export GCS_PULSE_API_KEY=<your-api-key>
export GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/sa.json

python book_room_event.py \
  --title "Q4 Planning" \
  --start "2026-10-15T10:00:00+09:00" \
  --end   "2026-10-15T12:00:00+09:00" \
  --attendees alice@example.com bob@example.com
```

### Python API

```python
from book_room_event import run

result = run(
    title="Q4 Planning",
    start="2026-10-15T10:00:00+09:00",
    end="2026-10-15T12:00:00+09:00",
    attendees=["alice@example.com"],
    room_preference="large",
    dry_run=True,   # False로 변경 시 실제 예약
)
print(result.status, result.booking_id)
```

## 환경변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `GCS_PULSE_API_URL` | 아니오 | GCS-PULSE 서버 URL (미설정 시 mock 모드) |
| `GCS_PULSE_API_KEY` | 아니오 | Bearer 인증 키 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 아니오 | GCP 서비스 계정 JSON 파일 경로 (미설정 시 mock) |
| `GOOGLE_CALENDAR_ID` | 아니오 | 대상 캘린더 ID (기본값: `primary`) |
| `GOOGLE_IMPERSONATE_EMAIL` | 아니오 | 서비스 계정 위장 이메일 |

## 반환값 (SkillResult)

| 필드 | 타입 | 설명 |
|------|------|------|
| `status` | str | `success` / `dry_run_ok` / `partial_failure` / `failed` |
| `booking_id` | str | GCS-PULSE 예약 ID |
| `event_id` | str | Google Calendar 이벤트 ID |
| `room_id` | str | 예약된 회의실 ID |
| `calendar_link` | str | Calendar 이벤트 직접 링크 |
| `errors` | list[str] | 오류 및 경고 메시지 |

## 오류 처리

- **회의실 없음:** `room_preference` 조건 완화 후 재시도 (최대 `MAX_FALLBACK_ATTEMPTS=3`)
- **예약 실패:** 다음 후보 회의실로 자동 전환
- **Calendar 실패:** GCS-PULSE 예약 자동 롤백 (`cancel_booking()`)
- **네트워크 오류:** `httpx` 타임아웃 (조회 10s, 예약 15s), 가용성 확인 실패 시 가용 처리

## 테스트 결과

| 시나리오 | 모드 | 결과 | 일시 |
|----------|------|------|------|
| dry-run (large room, 1 attendee) | mock | `dry_run_ok` | 2026-10-08 |
| dry-run (no preference, 2 attendees) | mock | `dry_run_ok` | — |
| fallback (unavailable primary) | mock | `dry_run_ok` | — |
| rollback (calendar fail simulation) | mock | rollback 정상 | — |
| dry-run CLI (Q4 Planning) | mock | `dry_run_ok` | 2026-10-08 |

**라이브 API 연결 상태:** `GCS_PULSE_API_URL=https://app.1000.school` 설정 완료.  
실제 예약 테스트는 사용자 확인 후 실행 가능.

## GCS-PULSE API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/meeting-rooms` | 회의실 목록 |
| `GET` | `/meeting-rooms/{room_id}/reservations?date=YYYY-MM-DD` | 예약 현황 조회 |
| `POST` | `/meeting-rooms/{room_id}/reservations` | 예약 생성 |
| `DELETE` | `/meeting-rooms/reservations/{reservation_id}` | 예약 취소 |

## 의존성

```
google-api-python-client>=2.100.0
google-auth>=2.23.0
httpx>=0.27.0
```
