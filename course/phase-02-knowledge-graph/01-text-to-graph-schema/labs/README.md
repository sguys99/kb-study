# 핸즈온 — 텍스트 → 그래프 스키마 설계

CQ 에서 스키마를 역설계하고, 그 스키마를 CQ 로 다시 검증한다. LLM·DB 가 없어 키 없이 로컬에서 돈다.

## 사전 준비

```bash
cd course/phase-02-knowledge-graph/01-text-to-graph-schema/practice
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 는 `pydantic>=2`, `pyyaml>=6` 뿐이다. API 키 불필요.

---

## step 1 — 골든 질문을 CQ 로 옮겨 적기

Phase 1/06 의 골든 질문, 특히 멀티홉 질문을 본다. "둘 이상 문서를 이어야 답이 되는" 것이
그래프가 필요한 CQ 의 핵심 시드다.

```bash
grep -A3 "type: multi-hop" ../../../phase-01-source-layer/06-baseline-hybrid-rag/practice/golden_questions.yaml
```

예상 출력(발췌):

```
    type: multi-hop
  - id: gq08
    question: "Self-RAG 와 CRAG 는 검색 품질 문제를 각각 어떻게 보정하나?"
    expected_source_ids: ["src-02-self-rag", "src-03-crag"]
```

이 질문이 `competency_questions.yaml` 의 cq08 로 옮겨졌다. 무엇이 추가됐는지 확인한다.

```bash
grep -A6 "id: cq08" competency_questions.yaml
```

예상 출력:

```
  - id: cq08
    question: "Self-RAG 와 CRAG 는 검색 품질 문제를 각각 어떤 기법으로 보정하며, 둘은 어떻게 비교되나?"
    type: multi-hop
    source_gq: gq08
    node_types: ["Model", "Method"]
    relation_types: ["USES", "COMPARES_TO"]
    answer_shape: "두 Model 의 Method 비교(경로)"
```

골든 질문에 없던 `node_types`·`relation_types`·`answer_shape` 가 붙었다. 이게 역설계의 산물이다.

---

## step 2 — 스키마 모델 실행: 샘플 노드/관계/클레임 검증

```bash
python3 graph_schema.py
```

예상 출력(앞부분):

```
=== 허용 노드 타입 ===
Method, Model, Dataset, Metric, Paper, Concept, Organization, Tool
=== 허용 관계 타입 ===
PROPOSES, IMPROVES, EVALUATED_ON, MEASURED_BY, COMPARES_TO, USES, CITES
=== 샘플 추출 묶음 검증 OK — JSON ===
{
  "entities": [
    {
      "name": "LightRAG",
      "type": "Model",
      "aliases": [],
      "provenance": {
        "source_id": "src-05-lightrag",
        "version": "v1@ab12cd34",
        "start": 120,
        "end": 168,
        "quote": "LightRAG supports naive, local, global, hybrid, mix"
      }
    },
    ...
  ],
  "claims": [
    {
      "subject": "LightRAG",
      "predicate": "reduces_token_cost",
      "object": "GraphRAG",
      "value": "99%",
      ...
    }
  ],
  ...
}
```

JSON 이 나왔다 = 모든 샘플이 Pydantic 검증을 통과했다. 모든 노드·관계·클레임에
`provenance`(source_id/version/start/end/quote)가 달린 걸 확인한다.

---

## step 3 — CQ 로 스키마 검증(커버리지 리포트)

```bash
python3 validate_schema.py
```

예상 출력:

```
스키마 통제 어휘 — 노드 8종 / 관계 7종
CQ 12건 커버리지 점검

  [PASS]   cq01  (single-hop)
  [PASS]   cq02  (single-hop)
  [PASS]   cq03  (single-hop)
  [PASS]   cq04  (single-hop)
  [PASS]   cq05  (single-hop)
  [PASS]   cq06  (single-hop)
  [PASS]   cq07  (single-hop)
  [PASS]   cq08  (multi-hop)
  [PASS]   cq09  (multi-hop)
  [PASS]   cq10  (multi-hop)
  [PASS]   cq11  (multi-hop)
  [PASS]   cq12  (multi-hop)

커버리지: 12/12 = 100%
모든 CQ 가 현재 스키마로 답 가능 — 추출 단계로 넘어가도 된다.
```

100% 가 나오면 스키마가 모든 CQ 를 받아낼 수 있다는 뜻이다. 추출 전에 이걸 본다.

---

## step 4 — 일부러 깨뜨려 품질 게이트 체감

스키마에 없는 관계 타입을 CQ 에 넣으면 어떻게 되나. 검증기가 잡아내야 한다.
임시 CQ 파일을 만들어 본다.

```bash
cat > /tmp/broken_cq.yaml <<'EOF'
questions:
  - id: cqX
    question: "RAG 를 인용한 논문은 어떤 기관 소속인가?"
    type: multi-hop
    node_types: ["Paper", "Organization"]
    relation_types: ["CITES", "AUTHORED_BY"]
    answer_shape: "Organization 엔티티"
EOF
python3 validate_schema.py /tmp/broken_cq.yaml
```

예상 출력:

```
스키마 통제 어휘 — 노드 8종 / 관계 7종
CQ 1건 커버리지 점검

  [REJECT] cqX  (multi-hop)  missing relation_types=['AUTHORED_BY']

커버리지: 0/1 = 0%
미충족 CQ: ['cqX']
→ 스키마에 빠진 타입/관계를 추가하거나 CQ 를 조정하라(둘 중 하나).
```

`AUTHORED_BY` 는 enum 에 없다 → cqX 가 REJECT 됐다. 종료 코드도 0 이 아니다.

```bash
echo "exit code: $?"
```

예상 출력:

```
exit code: 2
```

이게 품질 게이트의 가장 단순한 형태다. 빠진 관계를 발견했으니 선택지는 둘이다.
`RelationType` 에 `AUTHORED_BY` 를 추가하든지, 그 CQ 를 범위 밖으로 빼든지.
어느 쪽이든 **추출을 시작하기 전에** 결정한다 — 추출하고 나서 알면 다시 돌려야 한다.
