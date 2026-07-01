# 5.5 Answer-time Semantic · Access · Policy Check

> **Phase 5 · 토픽 05** · 04 까지 만든 어휘·canonical id·제약 엔진 위에, 답변을 내보내기 직전 검색 컨텍스트를 의미·권한·정책 세 게이트로 거른다. 통과한 것만 인용하고, 막힌 것은 사유와 함께 감사 로그로 남긴다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 적재 시점(04) 검증과 답변 시점(answer-time) 검증이 왜 다른 문제인지 설명하고, 답변 시점에만 개입하는 검사(사용자 권한·개념 폐기·출처 정책)를 구분한다.
- 세 게이트(semantic / access / policy)를 각각 구현한다 — 04 rule_engine 재검증 + 어휘 status, ACL vs principal, `policy_rules.yaml` 적용.
- `answer_time_check(context, principal)` 파이프라인을 만들어 retrieved context 를 `allowed` 와 `blocked[reason]` 으로 나누고, 민감 필드를 마스킹한다.
- 모든 결정을 `item_id·gate·decision·reason` 형태의 감사 가능한 decision log 로 남긴다.

**완료 기준**: `answer_time_check(context, principal={role:'analyst', tenant:'team-a'})` 가 internal-only 문서를 access 사유로, deprecated 개념·provenance 없는 트리플·저신뢰 항목을 policy/semantic 사유로 각각 `blocked` 에 넣고, 통과분만 `allowed` 로 반환하며 gate×decision decision_log 를 출력하면 완료.

---

## 1. 왜 답변 시점에 또 검증하나

04 에서 적재 직전에 노드·트리플을 검증했다. domain/range 를 맞추고, canonical id 를 강제하고, 미등록 관계를 걸러 냈다. 깨끗한 그래프가 들어갔다. 그렇다고 그게 곧 "이 사용자에게, 이 질문에, 이 근거를 답으로 내보내도 된다"는 뜻은 아니다.

세 가지가 적재 이후에 끼어든다.

첫째, **권한**이다. 그래프에 담긴 사실이 옳다고 해서 아무나 봐도 되는 건 아니다. 어떤 문서는 admin 전용이고, 어떤 노드는 team-a 만 접근한다. 검색기는 관련성만 보지 권한은 보지 않는다. Phase 1 의 Document Data Contract 에서 설계한 `acl`·`provenance` 가 바로 이 순간을 위한 것이었다.

둘째, **개념의 수명**이다. 적재 땐 멀쩡했던 개념이 나중에 폐기(deprecated)될 수 있다. `naive-rag` 는 과거 문서가 참조하니 어휘에 남겨 둔다. 하지만 답변에 인용하면 안 된다. 검색은 "관련 있으니까" 이걸 끌어오지만, 폐기 여부는 검색의 관심사가 아니다.

셋째, **조직 정책**이다. 출처 없는 주장은 답에 넣지 않는다. 민감 필드는 가린다. 신뢰도 낮은 추출은 뺀다. 이건 그래프의 옳고 그름과 별개인, 답변 산출물에 대한 규칙이다.

그래서 답변 직전에 게이트를 하나 더 둔다. 검색이 끌어온 컨텍스트를 그대로 LLM 에 넘기지 않고, **의미·권한·정책** 세 관점으로 한 번 더 거른다. 통과한 것만 답변 근거로 쓰고, 막힌 것은 왜 막혔는지 기록한다. 이 기록이 감사 추적(audit trail)의 핵심이다.

## 2. 세 게이트 — 같은 항목, 다른 관점

입력은 하나다. 검색이 끌어온 항목(문서 또는 트리플) 각각에 메타가 붙어 있다. `acl`(누가 볼 수 있나), `provenance`(어디서 왔나), `concept_ids`(무슨 개념을 가리키나), `confidence`(얼마나 믿을 만한가). 여기에 요청자 `principal`(role·tenant)이 더해진다.

세 게이트는 이 같은 항목을 서로 다른 눈으로 본다.

**(A) Semantic Gate — 의미상 여전히 유효한가.** 참조 개념이 어휘에 있는가. `status` 가 deprecated 는 아닌가(표시만 하고 최종 배제는 policy 가 한다). 그리고 트리플이면 04 의 rule_engine 을 답변 시점에 **다시** 돌린다. 적재 때 통과했어도, 검색이 방향 뒤집힌 트리플을 끌어올 수 있기 때문이다.

**(B) Access Gate — 이 사용자가 볼 권한이 있는가.** 항목의 `acl` 과 `principal` 을 대조한다. `visibility=public` 이면 통과. `internal` 이면 `acl.roles` 에 principal.role 이 있어야 한다. tenant 가 지정돼 있으면 principal.tenant 도 일치해야 한다(테넌트 격리).

**(C) Policy Gate — 정책상 인용해도 되는가.** `policy_rules.yaml` 을 읽어 판정한다. 출처 없으면 deny, 폐기 개념 참조면 deny, confidence 임계값 미만이면 deny, 민감 필드가 있으면 mask(항목은 쓰되 필드만 가림).

게이트는 순서대로 적용한다. 앞 게이트에서 deny 가 나오면 뒤는 볼 것도 없이 단락(short-circuit)한다. 결정은 `allow` / `deny` / `mask` 셋 중 하나다.

## 3. 실습 — 게이트 파이프라인

### 어휘에 수명주기(status)를 더한다

04 어휘에 필드 하나를 붙여 개념이 폐기됐는지를 담는다.

```python
# practice/controlled_vocabulary.py — ConceptEntry 에 추가된 필드
class ConceptEntry(BaseModel):
    concept_id: str
    entity_type: str
    preferred_label: str
    # ...
    # 05: active(기본) | deprecated(폐기: 답변 시 인용 금지). SKOS 개념 상태에 대응.
    status: str = "active"
```

`vocabulary.yaml` 의 `naive-rag` 에 `status: deprecated` 를 붙였다. 어휘에서 지우지는 않는다 — 과거 문서가 이 개념을 참조하기 때문이다. 답변 시점에만 막는다.

### 세 게이트를 각각 판정 함수로

각 게이트는 항목 하나를 받아 `PolicyDecision` 하나를 돌려준다. semantic 은 04 rule_engine 을 그대로 재사용한다.

```python
# practice/gates.py — SemanticGate 의 핵심
class SemanticGate:
    def check(self, item: dict) -> PolicyDecision:
        item_id = item["item_id"]
        # 참조 개념이 어휘에 있는지(미등록이면 의미 검증 실패)
        for cid in item.get("concept_ids", []):
            if self._concept(cid) is None:
                return PolicyDecision(item_id=item_id, gate="semantic", decision="deny",
                                      reason=f"UNKNOWN_CONCEPT: {cid!r} 가 vocabulary 에 없다")
        # 트리플이면 04 rule_engine 으로 domain/range 를 답변 시점에 재검증
        if item.get("kind") == "triple":
            triple = {"subject": item["subject"], "rel": item["rel"], "object": item["object"]}
            reasons = self.engine.check_triples([triple], self.nodes)
            violations = [r for r in reasons if r.severity == "violation"]
            if violations:
                v = violations[0]
                return PolicyDecision(item_id=item_id, gate="semantic", decision="deny",
                                      reason=f"SEMANTIC_VIOLATION[{v.rule_id}]: {v.message}")
        return PolicyDecision(item_id=item_id, gate="semantic", decision="allow")
```

access 는 acl 과 principal 을 대조한다.

```python
# practice/gates.py — AccessGate 의 핵심
class AccessGate:
    def check(self, item: dict, principal: dict) -> PolicyDecision:
        acl = item.get("acl") or {}
        visibility = acl.get("visibility", self.public_marker)
        if visibility != self.public_marker:                 # internal 이면 role 검사
            if principal.get("role") not in acl.get("roles", []):
                return PolicyDecision(item_id=item["item_id"], gate="access", decision="deny",
                                      reason=self.reason_role)
        tenants = acl.get("tenants")                          # tenant 격리
        if tenants and principal.get("tenant") not in tenants:
            return PolicyDecision(item_id=item["item_id"], gate="access", decision="deny",
                                  reason=self.reason_tenant)
        return PolicyDecision(item_id=item["item_id"], gate="access", decision="allow")
```

policy 는 `policy_rules.yaml` 을 순서대로 적용한다(출처 → 폐기 → 신뢰도 → 마스킹).

### 오케스트레이터 — allowed / blocked / decision_log

```python
# practice/answer_time_check.py — 파이프라인의 핵심
def run(self, items, principal) -> AnswerTimeResult:
    result = AnswerTimeResult()
    for item in items:
        for gate_name, decision in self._pipeline(item, principal):  # semantic→access→policy
            result.decision_log.add(decision)
            if decision.decision == "deny":
                result.blocked.append(BlockedItem(item_id=item["item_id"],
                                                  gate=gate_name, reason=decision.reason or ""))
                break                                        # 이후 게이트 단락
            if decision.decision == "mask":
                result.allowed.append(apply_mask(item, decision.masked_fields, self.mask_token))
                break
        else:
            result.allowed.append(item)                      # 모든 게이트 allow
    return result
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조. 이 토픽은 API 키·Neo4j 없이 로컬(Pydantic·PyYAML)에서만 돈다. 상용 LLM 을 붙일 지점이 없어 비용 대안 분기가 따로 필요 없다(답변 생성 단계에서 LLM 을 쓴다면 그때 Ollama + `bge-m3` 로 바꿔도 파이프라인은 동일하다).

## 4. 결과 해석

`principal={role: 'analyst', tenant: 'team-a'}` 로 8건을 돌리면 이렇게 갈린다.

```
-- allowed --
  ALLOW ctx-01   Self-RAG 는 PopQA 로 평가된다.
  ALLOW ctx-07   ... fields={'raw_score': '***', 'author_email': '***'}
-- blocked --
  DENY  ctx-02   [access]   ACL_ROLE_DENIED (roles=['admin'], principal.role='analyst')
  DENY  ctx-03   [policy]   DEPRECATED_CONCEPT (concept=naive-rag)
  DENY  ctx-04   [policy]   PROVENANCE_MISSING
  DENY  ctx-05   [policy]   LOW_CONFIDENCE (confidence=0.42 < 0.6)
  DENY  ctx-06   [semantic] SEMANTIC_VIOLATION[UsesShape]: USES 는 (:Method)-[:USES]->(:Dataset)
  DENY  ctx-08   [access]   ACL_TENANT_DENIED (tenants=['team-b'], principal.tenant='team-a')
```

각 게이트가 자기 관점에서 정확히 한 건씩(또는 두 건)을 잡았다. ctx-02 는 admin 전용이라 analyst 가 못 본다. ctx-08 은 role 은 맞지만 tenant 가 다르다. ctx-03 은 폐기된 `naive-rag` 를 인용하려 했다. ctx-06 은 04 에서 걸렸을 법한 방향 뒤집힌 트리플인데, 검색이 굳이 끌어와서 답변 시점에 다시 걸렸다. ctx-07 은 통과하되 민감 필드가 `***` 로 가려진다.

마지막에 gate×decision 집계가 붙는다. 이 집계가 감사의 출발점이다. "이번 답변에서 access 로 2건, policy 로 3건이 막혔다"를 한눈에 본다. `item_id·gate·decision·reason` 이 붙은 decision_log 는 Phase 6 관측성에서 그대로 트레이스로 흘려보내고, Phase 7 Agent 에서는 정책 도구의 반환값으로 쓴다.

왜 이게 중요한가. 게이트 없이 검색 결과를 바로 LLM 에 넘기면, 권한 없는 문서가 답에 새고, 폐기된 개념이 인용되고, 출처 없는 주장이 사실처럼 나간다. 그리고 무엇보다 **왜 그 답이 나왔는지 사후에 설명할 수 없다.** 게이트는 답변 품질을 지키는 동시에, 모든 인용을 감사 가능하게 만든다.

---

## 🚨 자주 하는 실수

1. **적재 시점 검증(04)으로 충분하다고 여긴다** — 적재 때 통과한 그래프라도 답변 시점의 관점은 다르다. 권한은 사용자마다 바뀌고, 개념은 나중에 폐기되며, 검색은 방향 뒤집힌 트리플도 관련성만 높으면 끌어온다. 04 는 "그래프가 옳은가", 05 는 "이 사용자에게 이 근거를 답으로 내보내도 되는가"다. 둘은 겹치지 않는다.
2. **deprecated 개념을 어휘에서 지운다** — 지우면 과거 문서·트리플이 참조하던 개념이 미등록(UNKNOWN_CONCEPT)으로 뒤바뀌어 엉뚱한 사유로 막힌다. 폐기는 삭제가 아니라 `status` 표시다. 어휘엔 남기고 답변 시점에만 배제한다.
3. **막힌 항목을 조용히 버린다** — blocked 를 로그 없이 버리면, 나중에 "왜 이 문서가 답에 안 나왔나"를 설명할 수 없다. deny 마다 `item_id·gate·reason` 을 남겨야 감사가 성립한다. mask 도 어느 필드를 가렸는지 기록한다.

## Phase 5 를 마치며

01 에서 온톨로지·시맨틱 레이어가 왜 필요한지 봤다. 02 에서 통제 어휘로 표기를 하나로 접었고, 03 에서 canonical id 로 같은 개체에 불변 식별자를 줬다. 04 에서 SHACL 스타일 제약으로 적재 직전 그래프를 검증했고, 05 에서 답변 직전 게이트로 의미·권한·정책을 집행했다. 어휘 → 식별 → 적재 검증 → 답변 게이트 — 시맨틱 레이어가 데이터의 생애 양끝(들어올 때와 나갈 때)을 모두 통제하는 그림이 완성됐다.

이제 남은 질문은 하나다. 이 모든 게 실제로 답변 품질을 올렸는가, 그리고 다음 변경이 그걸 깨뜨리지 않는가. Phase 6 은 그 답을 측정한다 — 평가·관측성·회귀 게이트.

## 출처

- W3C SHACL (Shapes Constraint Language): https://www.w3.org/TR/shacl/
- pySHACL: https://github.com/RDFLib/pySHACL
- Pydantic: https://docs.pydantic.dev/
- SKOS (Simple Knowledge Organization System) — 개념 상태·수명주기: https://www.w3.org/TR/skos-reference/
- When Large Language Models Meet Knowledge Graphs for Question Answering (Survey): arXiv [2505.20099](https://arxiv.org/abs/2505.20099)

## 다음 토픽

→ [6.1 Evaluation Pyramid](../../phase-06-evaluation-observability/01-evaluation-pyramid/lesson.md)

