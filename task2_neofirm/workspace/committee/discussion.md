# AI Committee Discussion
**NeoFirm × College Admissions Consulting**
**Date:** 2026-10-09
**Triggered by:** D00 — Split decision (Market=HOLD, Technology=HOLD, Business=INVEST)
**Format:** Challenger/Defender + Issue-by-Issue Resolution

---

## Opening Positions

**Market Reviewer (HOLD):** Pain은 5점이다. 하지만 유료 전환율이 0%인지 30%인지 모르는 상태에서 투자는 너무 이르다. 고객 검증 데이터가 전혀 없다.

**Technology Reviewer (HOLD):** 기술은 가능하다. 그러나 팀이 없다. execution_feasibility 1점이 모든 것을 말한다. 아이디어가 아무리 좋아도 실행할 사람이 없으면 투자 대상이 아니다.

**Business Reviewer (INVEST — Conditional):** 비즈니스 모델 설계 품질이 뛰어나다. Pain과 모델의 정합성, 연간 코호트 구조, 데이터 플라이휠 잠재력 — 이것은 팀과 파일럿을 확보하는 순간 강력한 INVEST가 된다. 지금 INVEST한다는 것은 팀 구성과 파일럿을 조건으로 한다.

---

## Round 1: Market Reviewer Challenges Business Reviewer

**Market Reviewer (Challenger):**
Business Reviewer의 "Conditional INVEST"는 사실상 HOLD다. "팀이 구성되고 파일럿이 완료되면 INVEST"라는 말은 "지금은 투자하지 말라"와 같다. 더 구체적으로:

핵심 질문: 무료 AI 진단 → 유료 전환율이 5%라면 이 비즈니스가 작동하는가? 25%라면? 이 숫자 없이 "비즈니스 모델이 좋다"는 평가가 의미 있는가?

특히 E13이 문제다. "무료 고객 중 몇 %가 유료로 전환하는지 데이터 없음"이라고 우리가 직접 확인했다. 전환율이 사업의 생존 변수인데, 이것을 모르는 상태에서 INVEST를 추천할 수 있는가?

**Business Reviewer (Defender):**
전환율 논점에 대한 반론:

1. **무료→유료 전환율의 성격이 다르다:** 입시 컨설팅은 "무료 서비스를 편의 기능으로 업그레이드하는" SaaS가 아니다. "진학이라는 불가역적 결정"을 앞둔 학부모가 무료 AI 분석을 받고 "수시 6장을 어디에 넣을지 전문가와 함께 결정하고 싶다"는 것은 매우 자연스러운 전환 경로다. 전환율이 3%인 B2C SaaS와 같은 기준으로 보면 안 된다.

2. **비교 기준:** 기존 입시 컨설팅 고객들은 어디서 오는가? 지인 소개, 학원 연계, 검색이다. 무료 AI 진단이 "나 이런 상황이야 — 전략 필요해"라는 명확한 시그널을 주는 고객을 직접 필터링하는 채널이다. 이것은 일반 광고 대비 훨씬 높은 전환율을 기대할 수 있다.

3. **Conditional INVEST의 의미:** 나의 INVEST는 "지금 당장 돈을 써라"가 아니라 "이 기회를 놓치지 말고 마일스톤 기반으로 진입하라"는 의미다. 전환율 측정은 5건의 파일럿 후에 가능하다 — 이것은 90일 이내에 가능하다.

**Market Reviewer (Response):**
Business Reviewer의 반론 중 "전환 경로의 자연스러움" 논점은 인정한다. 입시는 불가역적 고위험 결정이므로 전환율이 일반 SaaS보다 높을 가능성은 있다. 그러나 "높을 가능성"과 "실제로 높다"는 다르다. HOLD 입장을 유지하되, **전환율 측정 조건을 투자 조건에 포함하는 것**에 동의한다.

---

## Round 2: Technology Reviewer Challenges Business Reviewer

**Technology Reviewer (Challenger):**
Business Reviewer는 "팀 구성 확인 + 10건 파일럿"을 INVEST 조건으로 제시한다. 그러나 기술 관점에서 이 조건이 충분한지 의문이다:

핵심 질문: **수시 6장 AI 자동 생성의 품질 임계값은 무엇인가?** (E15 참조)

입시 컨설팅의 핵심 가치는 "내 상황에 맞는 정확한 6장 전략"이다. AI가 생성한 후보군이 전문가 판단 대비 75% 수준인지 95% 수준인지에 따라 서비스 가치가 완전히 달라진다. 10건 파일럿으로 이것을 측정할 수 있는가? 어떤 지표로?

더 근본적으로: 이 서비스의 핵심 기술 자산은 "합불 데이터로 훈련된 AI"인데, 초기에는 이 데이터가 없다. **Cold Start 문제를 어떻게 해결하는가?**

**Business Reviewer (Defender):**
Cold Start 문제와 AI 품질 임계값에 대한 반론:

1. **Cold Start 해결책이 비즈니스 모델에 내재되어 있다 [SOURCE] (E04, E05):**
   - NeoFirm은 Day 1부터 "AI 단독"이 아닌 "AI + 전문가"로 출발한다
   - 초기에는 AI가 기본 분석(대학/전형 비교, 지원 가능성 계산)만 담당하고 전문가가 전략 대부분을 결정한다
   - 전문가의 결정 과정이 곧 훈련 데이터가 된다
   - 즉, Cold Start는 "전문가 의존도 높음 → 데이터 축적 → AI 의존도 점진적 증가"로 자연스럽게 해결된다

2. **AI 품질 임계값 측정 방법:**
   - 10건 파일럿에서 전문가가 AI 추천을 얼마나 수정했는가를 기록한다
   - AI 수정률이 20% 이하면 AI 품질이 충분한 수준
   - 이것은 10건으로 초기 신호를 얻기에 충분하다

3. **MVP는 기술이 아닌 비즈니스 검증이다:** 초기 10건은 "AI가 완벽하다"는 것을 증명하는 게 아니라 "학부모가 돈을 낸다"와 "전문가와 AI의 협업 구조가 작동한다"를 검증하는 것이다.

**Technology Reviewer (Response):**
"전문가 의존도 높음 → 데이터 축적 → AI 의존도 증가"라는 단계적 접근은 기술적으로 타당하다. Cold Start 문제를 이 방식으로 우회하는 것은 현실적이다. 단, **파일럿 10건에서 전문가 수정률 기록을 의무화하는 것을 투자 조건에 포함**해야 한다.

---

## Round 3: Committee Challenge — Business Reviewer의 핵심 주장 심층 검증

**Market Reviewer (Challenging Business Reviewer's strongest positive claim):**
Business Reviewer의 가장 강한 주장: **"이것은 팀과 파일럿을 확보하는 순간 강력한 INVEST가 된다."**

이 주장을 입증하려면: 팀 + 파일럿이 확보되면 왜 HOLD가 아닌 INVEST인가? 팀과 파일럿이 생겨도 다음 불확실성들이 남는다:
- 전환율이 검증되어도 CAC(고객획득비용)가 LTV를 초과할 수 있다
- 입시 시즌 집중성 문제 — 8-11월 피크, 나머지 시간 수익 없음
- 매년 입시 제도가 변한다 — 유지보수 비용이 지속 발생한다

**Business Reviewer (Defending the claim):**
세 가지 반론:

1. **CAC < LTV 조건은 파일럿에서 측정 가능하다:** 무료 AI 진단의 배포 비용(SEO, SNS)이 얼마이고, 전환된 고객의 LTV(시즌 당 상담료)가 얼마인지는 10건 파일럿 후 계산 가능하다. 이것이 파일럿의 핵심 목적 중 하나다.

2. **계절성은 리스크가 아닌 특성이다:** 고3 입시는 8-11월 수시에 집중되지만, 이것은 예측 가능하고 반복 가능한 계절성이다. 학원 사업도, 보험 사업도 계절성이 있다. 매년 코호트가 재발생한다는 점에서 오히려 예측 가능한 수익 구조다. "12월-7월은 고2→고3 전환 준비, 모의고사 분석 서비스"로 비수기를 채울 수도 있다.

3. **입시 제도 변경 유지보수는 모든 에듀테크의 공통 비용이다:** NeoFirm만의 리스크가 아니다. 그리고 이것은 **오히려 진입장벽이다** — 기존 데이터 기반 업체가 새 제도에 적응하는 속도가 신규 진입자보다 빠르다.

결론: 팀 + 파일럿이 확보되면 INVEST인 이유는 **비즈니스 모델의 핵심 불확실성(전환율, LTV/CAC)이 소규모 파일럿으로 측정 가능하기 때문**이다. 이 단계에서 잔존하는 불확실성은 스케일업 단계의 문제지, 투자 결정을 막을 이유가 아니다.

**Market Reviewer (Final response to challenge):**
Business Reviewer의 계절성 반론은 설득력이 있다. 코호트 재발생 구조가 예측 가능한 수익이라는 점은 동의한다. **단, CAC/LTV 측정을 파일럿 조건에 반드시 포함해야 한다는 점을 재확인한다.**

**Technology Reviewer (Final position):**
Cold Start 해결 방식과 단계적 접근에는 동의한다. **파일럿 10건에서 전문가 수정률과 학부모 만족도를 동시에 측정하는 것을 조건으로 제시한다.**

---

## Issue-by-Issue Resolution Status

| 이슈 | 토론 결과 | 해결 여부 |
|------|----------|----------|
| D00: HOLD vs INVEST 결정 분열 | 시점 불일치 — 모두 파일럿 후 INVEST 동의, 시점 차이 | PARTIALLY RESOLVED |
| 유료 전환율 미검증 | Market이 전환 경로 자연성 인정; 파일럿에서 측정 조건 합의 | RESOLVED (조건부) |
| Cold Start 문제 | Technology가 단계적 접근(전문가→AI) 타당성 인정 | RESOLVED |
| AI 품질 임계값 | 전문가 수정률 기록 의무화로 합의 | RESOLVED (조건부) |
| 팀 없음 | 모든 리뷰어 동의 — 팀 확인이 1순위 조건 | RESOLVED (공통 조건) |
| CAC < LTV 검증 | 파일럿에서 측정 가능하다는 Business 반론 수용 | RESOLVED (조건부) |
| 계절성/입시 제도 변경 리스크 | Market이 Business의 계절성 반론 수용 | RESOLVED |

**UNRESOLVED:**
- 전문가 확보 가능성 (E14): 경험 있는 입시 컨설턴트 실제 모집 가능성 — 이것은 실행 단계의 현실 문제로 토론에서 해결 불가
- 규제 환경: 에듀테크 AI 서비스 관련 법적 리스크는 외부 전문가 검토 필요

---

## Committee Consensus

HOLD(Market) + HOLD(Technology) vs INVEST(Conditional, Business)의 분열은 **투자 시점에 대한 의견 차이**로, 비즈니스 모델 또는 시장 기회에 대한 근본적 불일치가 아니다.

세 리뷰어 모두 다음에 동의한다:
1. Pain은 구조적이고 크다
2. 비즈니스 모델 설계는 논리적으로 타당하다
3. 데이터 플라이휠이 잠재적 Moat이다
4. **지금 당장 투자하기에는 실행 증거가 너무 부족하다**
5. **다음 조건들이 충족되면 INVEST로 전환 가능하다:**
   - 창업팀 확인 (AI 엔지니어 + 입시 도메인 전문가)
   - 파일럿 10건 완료
   - 유료 전환율 측정
   - 전문가 수정률 기록
   - CAC/LTV 초기 계산

핵심 질문은 "이것이 되는 사업인가?"가 아닌 "지금 투자해야 하는가, 아니면 조건 충족 후 투자해야 하는가?"다.
