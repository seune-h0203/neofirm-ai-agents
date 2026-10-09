# GCS-PULSE 라이브 API 연결 테스트

## 사전 조건

```powershell
$env:GCS_PULSE_API_URL = "https://api.1000.school"   # ← 프론트(app.)가 아닌 API 서버
$env:GCS_PULSE_API_KEY = "<your-api-key>"             # 실제 키 입력 (파일에 저장 금지)
```

## 연결 확인 (meeting-rooms 조회)

```powershell
cd C:\Users\elice\neofirm\skills\room-booking
python -c "
import httpx, os
base = os.environ['GCS_PULSE_API_URL']
key = os.environ.get('GCS_PULSE_API_KEY', '')
r = httpx.get(f'{base}/meeting-rooms',
              headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
              timeout=10)
print('Status:', r.status_code)
print('Body:', r.text[:500])
"
```

## 예약 dry-run (외부 상태 변경 없음)

```powershell
python book_room_event.py `
  --title "GCS Live Test" `
  --start "2026-10-15T10:00:00+09:00" `
  --end   "2026-10-15T11:00:00+09:00" `
  --attendees elice0105412@gmail.com `
  --room-preference "small" `
  --dry-run --json
```

## 실제 예약 (실행 전 확인 필요)

```powershell
# GCS_PULSE_API_URL, GCS_PULSE_API_KEY 설정 후
python book_room_event.py `
  --title "GCS Live Test" `
  --start "2026-10-15T10:00:00+09:00" `
  --end   "2026-10-15T11:00:00+09:00" `
  --attendees elice0105412@gmail.com `
  --json
```

## 현재 연결 테스트 결과

| 항목 | 결과 |
|------|------|
| HTTPS 연결 | ✅ 200 OK |
| `app.1000.school/meeting-rooms` | HTML (Next.js 프론트엔드 — API 아님) |
| `api.1000.school/meeting-rooms` (인증 없음) | ✅ 401 JSON `{"detail":"Not authenticated"}` |
| `api.1000.school/meeting-rooms` (Bearer 인증) | ✅ 200 JSON — 회의실 14개 반환 |
| 예약 현황 조회 | ✅ 200 JSON — 날짜별 reservations 반환 |
| dry-run Skill 실행 | ✅ `dry_run_ok`, room_id=2 (N.MR2) 선택 |

> **주의:** API 키는 환경변수로만 설정하고 파일에 저장하지 마세요.
