# NeoFirm 생성 오류 디버그 기록

## 진단 일시
2026-10-07

## 재현 환경
- Python: `C:\Users\elice\AppData\Local\Python\pythoncore-3.14-64\python.exe`
- notebooklm-cli: 0.1.12
- nlm.exe 위치: `C:\Users\elice\AppData\Local\Python\pythoncore-3.14-64\Scripts\nlm.exe`

---

## 발견된 Root Causes

### 1. 명령어 순서 오류 (PRIMARY BUG)
**잘못된 코드:**
```python
NLM, "query", "notebook", NOTEBOOK_ID, question, "--json"
# → nlm query notebook <id> <question> --json
```

**올바른 문법:**
```
nlm notebook query <notebook_id> <question>
```

`nlm --help` 출력에 `query` 최상위 명령 없음.  
`nlm notebook --help`에서 `query` 서브커맨드 확인.

---

### 2. `--json` 플래그 없음
`nlm notebook query --help` 출력에 `--json` 옵션 없음.  
출력은 Rich console plain text.

---

### 3. JSON 파싱 오류
```python
data = json.loads(stdout.decode(...))  # stdout은 JSON이 아님
answer = data["answer"]               # KeyError 발생
```
→ stdout 전체를 text로 사용해야 함.

---

### 4. 인증 없음
```
$ nlm auth status
✗ Not authenticated
  Profile not found: default
```
`nlm auth list` → "No profiles found."

프로파일 저장 위치: `C:\Users\elice\AppData\Local\nlm\nlm\profiles\`  
→ 디렉토리 존재하지 않음.

**사용자 액션 필요: `nlm login` 실행 후 Google 계정으로 인증**

---

### 5. PATH 문제
- `shutil.which("nlm")` → `None` (PATH에 Scripts 미포함)
- `Path(sys.executable).parent / "Scripts" / "nlm.exe"` → **존재함**
- subprocess env에 Scripts 경로 추가 필요

---

## 수정한 파일
- `app.py`: 명령어 순서, JSON 파싱, PATH, 오류 메시지, 로깅 개선
- `generate.py`: 동일

## 수정 후 올바른 nlm 명령
```
nlm notebook query 61af6e10-ae3a-4e54-8da5-41302feebcef "<question>"
```

## 남은 블로커
- **nlm login 필요**: 인증 완료 전까지 모든 쿼리 실패
