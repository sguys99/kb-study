# Lab — Answer-time Semantic · Access · Policy Check

답변 직전, 검색이 끌어온 컨텍스트를 세 게이트(semantic / access / policy)로 걸러
allowed 만 답변에 인용하고 blocked 는 사유와 함께 감사 로그로 남긴다.

전제: Python 3.11+. API 키·Neo4j·Docker 불필요. 전부 로컬에서 돈다.
04 산출물(`controlled_vocabulary.py` · `rule_engine.py` · `reject_reason.py` · `shapes.yaml`)을
이 폴더 `practice/` 에 함께 복사해 뒀다. 05 는 그 위에 `policy_rules.yaml` · `gates.py` ·
`decision_log.py` · `answer_time_check.py` 를 얹는다.

---

## 0. 준비

```bash
cd practice
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

예상 출력(마지막 줄):

```
Successfully installed PyYAML-6.x pydantic-2.x pydantic-core-2.x ...
```

---

## 1. 재사용 부품 확인 — 어휘 status 필드

05 는 04 어휘에 개념 수명주기 상태(`status`)를 더했다. `naive-rag` 가 `deprecated` 다.

```bash
python controlled_vocabulary.py
```

예상 출력(끝부분):

```
== relation type 매핑 ==
  OK     'USES'           -> USES (uses, matched=preferred)
  ...
  REJECT 'MENTIONS'       -> NOT_IN_RELATION_TYPE_CATALOG: 카탈로그에 없는 타입(REJECT)

[assert] 모든 자체검증 통과
```

`vocabulary.yaml` 을 열어 `naive-rag` 항목에 `status: deprecated` 가 붙어 있는지 확인한다.

---

## 2. 결정 로그 포맷 확인

감사 로그 한 줄이 어떻게 생겼는지 먼저 본다.

```bash
python decision_log.py
```

예상 출력:

```
[ALLOW] ctx-01   gate=policy
[DENY ] ctx-02   gate=access    ACL_ROLE_DENIED: analyst 는 admin 문서 접근 불가
[MASK ] ctx-07   gate=policy    SENSITIVE_FIELD  fields=['raw_score']
...
[assert] 모든 자체검증 통과
```

---

## 3. 게이트 파이프라인 실행 (핵심)

`principal={role: analyst, tenant: team-a}` 로 `retrieved_context.json` 8건을 검사한다.

```bash
python answer_time_check.py
```

예상 출력(요지 — 순서·문구는 동일):

```
== answer-time check (principal: role=analyst, tenant=team-a) ==

-- allowed (답변에 인용 가능) --
  ALLOW ctx-01   Self-RAG 는 PopQA 로 평가된다.
  ALLOW ctx-07   Self-RAG 는 PopQA 에서 높은 정확도를 보고했다.  fields={'raw_score': '***', 'author_email': '***'}

-- blocked (배제 + 사유) --
  DENY  ctx-02   [access] ACL_ROLE_DENIED ... (roles=['admin'], principal.role='analyst')
  DENY  ctx-03   [policy] DEPRECATED_CONCEPT ... (concept=naive-rag)
  DENY  ctx-04   [policy] PROVENANCE_MISSING ...
  DENY  ctx-05   [policy] LOW_CONFIDENCE ... (confidence=0.42 < 0.6)
  DENY  ctx-06   [semantic] SEMANTIC_VIOLATION[UsesShape]: USES 는 (:Method)-[:USES]->(:Dataset) ...
  DENY  ctx-08   [access] ACL_TENANT_DENIED ... (tenants=['team-b'], principal.tenant='team-a')
```

읽는 법:

- **ctx-02 / ctx-08 (access)** — analyst 는 admin 전용(internal) 문서를 못 본다(ctx-02).
  role 은 맞아도 tenant 가 team-b 면 격리로 막힌다(ctx-08).
- **ctx-03 (policy·deprecated)** — `naive-rag` 는 어휘에 남아 있지만 `status=deprecated` 라 인용 금지.
- **ctx-04 (policy·provenance)** — 출처가 없는 주장은 답하지 않는다.
- **ctx-05 (policy·confidence)** — 0.42 는 임계값 0.60 미만이라 배제.
- **ctx-06 (semantic)** — 적재 땐 통과했을 수 있으나, 검색이 방향 뒤집힌 트리플을 끌어왔다.
  04 rule_engine 이 답변 시점에 다시 잡는다.
- **ctx-01 / ctx-07 (allow)** — 통과. ctx-07 은 민감 필드(`raw_score`·`author_email`)가
  `***` 로 가려진 채 인용된다.

---

## 4. decision_log 집계 (감사)

같은 실행의 마지막에 gate × decision 집계가 붙는다.

예상 출력:

```
== decision_log 집계 (gate × decision) ==
  access   allow 5건
  access   deny  2건
  policy   allow 1건
  policy   deny  3건
  policy   mask  1건
  semantic allow 7건
  semantic deny  1건

[assert] 모든 자체검증 통과
```

`[assert] 모든 자체검증 통과` 가 뜨면 완료 기준을 만족한 것이다.

---

## 5. 직접 실험 — principal 을 바꿔 본다

`principal.json` 의 `role` 을 `admin` 으로 바꾸고 다시 실행해 본다.

```bash
# principal.json 에서 "role": "analyst" -> "role": "admin" 으로 수정 후
python answer_time_check.py
```

기대: ctx-02(admin 전용)가 이제 access 를 통과한다. 단 ctx-08 은 tenant=team-b 라
role 을 admin 으로 바꿔도 tenant 격리로 여전히 막힌다(단, admin 은 tenant 도 team-a 여야 통과).
policy·semantic 게이트 결과(ctx-03/04/05/06)는 사용자와 무관하므로 그대로다.

> 이 실험이 세 게이트의 관점 차이를 보여준다. access 는 "누가 보나", policy·semantic 은
> "무엇을 인용하나"를 본다. `answer_time_check.py` 상단의 assert 는 analyst 기준이므로,
> role 을 바꾸면 assert 는 실패할 수 있다(의도된 것 — 실험 후 되돌린다).
