# NeoFirm NotebookLM CLI 설정 로그

**날짜:** 2026-10-06

---

## 1. 환경 확인

| 도구 | 버전 | 상태 |
|------|------|------|
| Python | 3.14.5 | ✅ 설치됨 |
| pip | 26.1.1 | ✅ 설치됨 |
| uv | 0.12.23 | ✅ 설치됨 (신규) |

## 2. uv 설치

- 설치 경로: `C:\Users\elice\.local\bin`
- PATH 추가: 세션 내 적용 완료

## 3. notebooklm-mcp-cli 설치

```
uv tool install notebooklm-mcp-cli
```

- 패키지: notebooklm-mcp-cli 0.15.3
- 설치된 실행파일: `nlm`, `notebooklm-mcp`
- 의존성: 83개 패키지

## 4. nlm --help 확인

- 상태: ✅ 정상 동작
- 주요 명령: login, auth, notebook, source, query, pipeline 등

## 5. 작업 폴더 생성

- `C:\Users\elice\neofirm\` ✅
- `C:\Users\elice\neofirm\logs\` ✅

## 6. Google 로그인

- 상태: ✅ 성공
- 계정: elice0105412@gachon.ac.kr
- 프로파일: default
- 쿠키: 46개 추출
- 저장 경로: `C:\Users\elice\.notebooklm-mcp-cli\profiles\default`

## 7. 인증 검증

- `nlm auth status`: auth subcommand에 status 없음 (login 성공으로 대체 확인)
- `nlm notebook list`: ✅ 19개 노트북 확인
  - **"Neofirm 2026: The Rise of AI-Driven Professional Service Firms"** (ID: `61af6e10-ae3a-4e54-8da5-41302feebcef`, 소스 1개)
  - 기타 노트북 18개

## 8. 설정 완료 요약

| 단계 | 상태 |
|------|------|
| Python/pip 확인 | ✅ |
| uv 설치 | ✅ 0.12.23 |
| notebooklm-mcp-cli 설치 | ✅ 0.15.3 |
| nlm --help 확인 | ✅ |
| 작업 폴더 생성 | ✅ `C:\Users\elice\neofirm\` |
| Google 로그인 | ✅ gachon.ac.kr |
| 노트북 목록 확인 | ✅ 19개 |

**NeoFirm 자동화 준비 완료.**

## 9. 자동화 스크립트 생성

- 파일: `C:\Users\elice\neofirm\generate.py`
- 기능: 전문서비스 영역을 입력하면 4가지 과제 결과물 자동 생성
  - 과제 A: 기존 가치사슬 해부 분석서
  - 과제 B: AI-전문가 작업 배분표
  - 과제 C: 1페이지 투자메모
  - 문제정의문
- 출력: `C:\Users\elice\neofirm\output\` (개별 .md + 통합 보고서)

**사용법:**
```powershell
cd C:\Users\elice\neofirm
python generate.py "노무 (근로계약·급여)"
python generate.py "법률 (상업계약)"
python generate.py "특허 (출원·명세서)"
```
