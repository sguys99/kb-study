# 그래프 스키마 카드 (Schema Card)

`graph_schema.py` 를 사람이 읽는 형태로 옮긴 것이다. 추출기·리뷰어가 같은 그림을 보게 한다.
대상 코퍼스는 AI/LLM 기술 문서 8건(Phase 1 과 동일): `src-01-rag` ~ `src-08-multihop`.

## 노드 타입 (NodeType)

| 라벨 | 의미 | 예시 | 지원 CQ |
|------|------|------|---------|
| `Method` | 기법·알고리즘 | Self-Reflection, Corrective Retrieval | cq02, cq03, cq08, cq09, cq10, cq12 |
| `Model` | 시스템·프레임워크 | RAG, Self-RAG, CRAG, LightRAG | cq01~cq04, cq08, cq09, cq11, cq12 |
| `Dataset` | 평가·학습 데이터셋 | — | cq12 |
| `Metric` | 평가 지표 | Recall, Faithfulness | cq12 |
| `Paper` | 논문·문서 | GraphRAG 논문 | cq04 |
| `Concept` | 개념 | 임베딩, 멀티홉, 커뮤니티 요약 | cq01, cq05~cq07, cq09, cq10 |
| `Organization` | 기관 | Microsoft, HKUDS | cq04 |
| `Tool` | 구현 도구·DB | Neo4j | cq06 |

## 관계 타입 (RelationType)

방향은 `(domain)-[TYPE]->(range)` 로 읽는다.

| 타입 | domain → range | 의미 | 지원 CQ |
|------|----------------|------|---------|
| `PROPOSES` | Paper/Organization → Method/Model | 무엇을 제안했나 | cq04 |
| `IMPROVES` | Method/Model → Method/Model | 무엇을 개선했나 | cq09, cq10, cq12 |
| `EVALUATED_ON` | Model → Dataset | 어디서 평가됐나 | cq12 |
| `MEASURED_BY` | Model/Method → Metric | 무엇으로 측정했나 | cq12 |
| `COMPARES_TO` | Model → Model | 무엇과 비교했나 | cq08, cq11 |
| `USES` | Model → Tool/Method | 무엇을 쓰나 | cq01~cq03, cq08~cq10 |
| `CITES` | Paper → Paper | 무엇을 인용했나 | (확장용 — 현재 CQ 미사용) |

## Claim — 근거·수치를 보존하는 주장 노드

단순 엣지로는 수치·근거가 흩어진다. "LightRAG 가 GraphRAG 대비 토큰 비용을 99% 줄였다"
같은 정량 주장은 주체·술어·대상·값·근거를 한 노드로 묶는다.

| 필드 | 의미 |
|------|------|
| `subject` | 주장의 주체 엔티티 |
| `predicate` | 술어. 예: `reduces_token_cost` |
| `object` | 대상(엔티티 또는 값). 예: GraphRAG |
| `value` | 정량 값. 예: `99%` |
| `provenance` | 근거 source span (필수) |

지원 CQ: cq11(수치+근거).

## Event — 시간·다자(n-ary) 관계 노드

참여자가 셋 이상이거나 시점이 핵심이면 엣지 하나로는 표현이 깨진다.
"2020년 RAG 가 NeurIPS 에서 발표됐다" → `participants=[RAG, NeurIPS]`, `time=2020`.

| 필드 | 의미 |
|------|------|
| `name` | 이벤트 이름. 예: `RAG_publication` |
| `participants` | 참여 엔티티 목록(1개 이상) |
| `time` | 발생 시점(ISO8601 권장) |
| `provenance` | 근거 source span (필수) |

지원 CQ: (확장용 — 시간성 질문을 추가하면 활성화).

## Provenance — 04 SourceSpan 호환

모든 노드·관계·클레임·이벤트가 매단다. 이게 있어야 다음 Phase(Neo4j 적재, GraphRAG 인용)
에서 답변→원문 역추적이 끊기지 않는다.

| 필드 | 04 대응 | 의미 |
|------|---------|------|
| `source_id` | SourceSpan.source_id | 근거 문서. `src-...` |
| `version` | DocumentContract.version | `v{n}@{hash}` |
| `start` / `end` | SourceSpan.start / end | 원문 문자 offset |
| `quote` | SourceSpan.quote | 검증용 인용 사본 |
