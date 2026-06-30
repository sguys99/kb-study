# 4.8 LightRAG + Neo4j 운영 — 증분·삭제·스토리지·캐시·동시성

> **Phase 4 · 토픽 08** · 07은 파일 기반으로 한 번 인덱싱하고 끝냈다. 운영은 거기서부터 시작이다. 그래프 스토리지를 Neo4j로 옮기고, 문서를 증분으로 더하거나 지우고, 캐시로 비용을 줄이고, 동시성을 조절한다. Phase 4의 마지막 토픽이다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- LightRAG의 스토리지 4종(KV·Vector·Graph·DocStatus)이 분리돼 있음을 이해하고, `graph_storage="Neo4JStorage"`로 그래프만 Neo4j로 옮긴다. 임베딩은 여전히 파일에 남는다는 경계를 직접 확인한다.
- 이미 적재된 그래프 위에 문서 1건만 `ainsert`로 증분 추가해, 재인덱싱 없이 Neo4j 노드·관계가 느는 것을 전후 수치로 측정한다.
- `await rag.adelete_by_doc_id(...)`로 문서 1건을 지우고, 고유 엔티티만 사라지고 공유 엔티티는 남는 정리 과정을 Cypher로 검증한다.
- 캐시(`enable_llm_cache`·추출 캐시)와 동시성 환경변수(`MAX_ASYNC_LLM`·`MAX_PARALLEL_INSERT` 등)를 조절해 재인덱싱·반복 질의 비용과 부하를 제어한다.

**완료 기준**: 그래프 스토리지를 Neo4j로 띄워 07 코퍼스를 적재한 뒤, 문서 1건을 증분 추가하면 재인덱싱 없이 Neo4j 노드·엔티티가 늘고, `adelete_by_doc_id`로 그 문서를 지우면 연결 엔티티·관계가 정리(공유 엔티티는 보존)되면 완료.

---

## 1. 왜 운영을 따로 배우나

07은 인덱싱을 한 번 돌리고 5모드 A/B로 끝났다. 저장소는 전부 파일이었다. 그래프는 `working_dir` 아래 GraphML, 벡터는 nano-vectordb. 데모로는 충분하지만 운영은 다르다.

코퍼스는 멈춰 있지 않다. 논문이 새로 올라오고, 잘못 들어간 문서를 빼야 하고, 여러 사람이 같은 그래프를 본다. 이때 파일 그래프의 한계가 드러난다. Cypher로 질의할 수 없고 시각화 도구도 없는 데다, 두 프로세스가 같은 파일을 동시에 건드리면 깨진다. 백업은 폴더 복사뿐이다.

그래서 운영에서는 그래프를 Neo4j로 뺀다. 07이 "재인덱싱·증분·삭제는 08에서"라고 미룬 게 정확히 이 영역이다. 다섯 축으로 나눠 본다. 스토리지 전환, 증분 적재, 삭제, 캐시, 동시성이다.

## 2. 스토리지 4종 — 무엇이 Neo4j로 가고 무엇이 안 가나

LightRAG의 저장소는 한 덩어리가 아니라 네 갈래로 나뉜다.

| 스토리지 | 담는 것 | 07(파일) | 08 |
|----------|---------|----------|-----|
| KV_STORAGE | 문서 정보·LLM 캐시 | 파일 | 파일(그대로) |
| VECTOR_STORAGE | 임베딩 | 파일 | 파일(그대로) |
| GRAPH_STORAGE | 엔티티·관계(그래프 구조) | 파일 | **Neo4j** |
| DOC_STATUS_STORAGE | 문서 처리 상태 | 파일 | 파일(그대로) |

이번에 바꾸는 건 GRAPH_STORAGE 하나, `graph_storage="Neo4JStorage"` 한 줄이다. 이게 핵심이자 가장 흔한 오해의 지점이다. 그래프만 Neo4j로 가고 **임베딩(Vector)은 여전히 파일에 남는다.** 벡터까지 옮기려면 별도의 vector_storage 백엔드를 따로 지정해야 한다. 그래프를 Neo4j로 옮겼다고 해서 검색 전체가 Neo4j 위에서 도는 건 아니다.

왜 하필 그래프만 빼나. Cypher로 직접 질의하고, Neo4j Browser로 시각화하고, 여러 프로세스가 동시에 접근하고, 백업을 DB 기능으로 한다. 운영에 필요한 게 다 그래프 쪽에 몰려 있어서다.

코드는 07과 거의 같다. 생성자에 인자 하나가 붙을 뿐이다.

```python
# practice/index_neo4j.py 의 핵심 부분
rag = LightRAG(
    working_dir=WORKING_DIR,
    graph_storage="Neo4JStorage",   # ← 08 의 전부. KG 만 Neo4j 로 (Vector/KV/DocStatus 는 파일)
    llm_model_func=llm_model_func,
    embedding_func=embedding_func,
    enable_llm_cache=True,                     # 질의 캐시
    enable_llm_cache_for_entity_extract=True,  # 추출 단계 캐시
)
await rag.initialize_storages()        # REQUIRED (07과 동일)
await initialize_pipeline_status()
```

Neo4j 연결은 환경변수로 준다. 넷 다 있어야 한다.

```bash
NEO4J_URI=neo4j://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j        # community edition 필수 — 빠뜨리면 연결 실패
```

> 백엔드 선택은 **문서를 넣기 전에** 끝내야 한다. 파일 그래프로 이미 인덱싱한 `working_dir`을 중간에 Neo4j로 바꿔 이어 쓸 수 없다. 새 `working_dir`/DB로 처음부터 인덱싱한다.

## 3. 증분 적재 — `ainsert`는 본 문서를 다시 안 뽑는다

운영의 일상은 "문서 한 건 추가"다. LightRAG는 문서 내용의 해시를 doc id로 쓴다. 같은 내용을 다시 `ainsert`하면 이미 처리한 문서로 보고 건너뛴다. 새 문서만 청킹하고 엔티티·관계를 뽑아 기존 그래프에 이어 붙이니, 전체 재인덱싱은 필요 없다.

07 코퍼스(01~03)가 이미 Neo4j에 들어가 있다고 하자. 여기에 04 한 건만 더한다.

```python
# practice/incremental_insert.py 의 핵심 부분
before = neo4j_counts()                       # {'nodes':.., 'relationships':..}
await rag.ainsert(text, file_paths="04-incremental-and-storage.md")  # 04 만, 01~03 은 스킵
after = neo4j_counts()
print_delta("Neo4j 그래프", before, after)    # nodes/relationships 가 늘었는지
```

이 상태를 추적하는 게 DocStatus 스토리지다. 문서는 pending → processing → processed로 가고, 추출이 깨지면 failed로 남는다. 증분이 제대로 됐다면 `processed`가 정확히 1 늘어야 한다.

## 4. 결과 해석 — 증분과 삭제는 대칭이 아니다

증분 후 출력은 이렇게 읽는다.

```
[Neo4j 그래프] 전후 비교
  nodes              34 ->  47   (+13)
  relationships      41 ->  63   (+22)
[DocStatus]
  processed           3 ->   4   (+1)
```

`processed +1`은 04만 처리됐다는 증거다. 01~03이 다시 추출됐다면 LLM 호출이 폭증했을 텐데, 캐시와 doc id 덕에 그런 일은 없다.

삭제는 `adelete_by_doc_id`로 한다. **async 전용이다.** 단순히 행 하나 지우는 게 아니라, 청크를 지우고 그 청크에만 연결된 엔티티·관계를 정리하고 고아가 된 엔티티를 치운 뒤 인덱스를 갱신한다.

```python
# practice/delete_ops.py 의 핵심 부분
doc_id = await resolve_doc_id(rag, "04-incremental-and-storage.md")  # 파일→doc id 역조회
await rag.adelete_by_doc_id(doc_id)   # async 전용. 청크→엔티티/관계→고아→인덱스 재구성
```

여기서 핵심은 줄어드는 폭이 늘어난 폭보다 **작다**는 점이다.

```
  nodes              47 ->  36   (-11)   # 증분 때 +13, 삭제 땐 -11
```

04와 01~03이 함께 쓰는 엔티티(LightRAG, Neo4j, 지식그래프)는 다른 문서가 아직 참조하니 남는다. 04에서만 나온 엔티티만 정리되는 셈이다. 그래서 삭제 폭이 곧 "04만의 고유 엔티티" 크기다. Cypher로 직접 확인할 수 있다.

```cypher
MATCH (n) WHERE n.entity_id CONTAINS 'Neo4j' RETURN n LIMIT 5;
// 04 를 지워도 02 가 참조하므로 남아 있다
```

## 5. 캐시와 동시성 — 비용과 부하를 다이얼로 돌린다

캐시는 두 곳에 있다. 질의 캐시(`enable_llm_cache`, 기본 True)는 같은 질문이 다시 오면 저장된 답으로 즉답한다. 추출 캐시(`enable_llm_cache_for_entity_extract`)는 같은 청크를 재추출할 때 LLM 호출을 아낀다. 둘 다 KV 스토리지에 저장된다. 방금 지운 04를 다시 증분하면 추출 캐시 적중 로그가 보인다.

동시성은 환경변수 네 개로 조절한다. 상용 API 레이트리밋과 Neo4j 동시 쓰기 부하를 함께 봐야 하니, 낮게 시작해 올린다.

```bash
MAX_ASYNC_LLM=8              # 동시 LLM 호출 상한
MAX_PARALLEL_INSERT=3        # 동시 인덱싱 문서 수
EMBEDDING_FUNC_MAX_ASYNC=16  # 임베딩 동시성
EMBEDDING_BATCH_NUM=32       # 임베딩 배치 크기
```

한 가지 예외가 삭제다. 파괴적 연산이라 동시성과 무관하게 직렬화된다. 삭제가 도는 동안에는 새 enqueue가 막힌다. 그래프 일관성을 지키기 위한 설계다.

> 전체 코드와 실행 절차는 [`practice/`](practice/)와 [`labs/`](labs/) 참조.
> 비용을 줄이려면 Ollama + `bge-m3` 대안 분기를 따른다(`.env`의 OLLAMA 블록, `BACKEND=ollama`).

---

## 🚨 자주 하는 실수

1. **`graph_storage`만 바꾸고 "벡터도 Neo4j로 갔다"고 착각** — 그래프(엔티티·관계)만 Neo4j로 간다. 임베딩은 그대로 `working_dir` 파일에 남는다. `rag_storage` 폴더에 `vdb_*.json`이 여전히 있는 걸 확인하면 분명해진다. 벡터까지 옮기려면 vector_storage 백엔드를 따로 지정해야 한다.
2. **백엔드를 중간에 바꿔 이어 쓰려 함** — 파일 그래프로 인덱싱한 `working_dir`을 그대로 두고 `graph_storage`만 Neo4j로 바꾸면 기존 그래프가 안 따라온다. 백엔드는 문서 추가 전에 정하고, 바꾸려면 새 DB/working_dir로 처음부터 인덱싱한다.
3. **`NEO4J_DATABASE` 누락** — community edition은 이 값이 필수다. 빠뜨리면 연결 단계에서 실패한다. URI·계정·비밀번호만 채우고 데이터베이스명을 잊는 실수가 잦다.
4. **삭제를 동기로 호출** — `adelete_by_doc_id`는 async 전용이다. `await` 없이, 또는 동기 메서드인 줄 알고 부르면 동작하지 않는다. 삭제는 항상 `await rag.adelete_by_doc_id(...)`.
5. **동시성을 처음부터 너무 높임** — `MAX_ASYNC_LLM`·`MAX_PARALLEL_INSERT`를 크게 잡으면 상용 API 레이트리밋에 걸리거나 Neo4j 쓰기 락이 충돌한다. 낮게 시작해 로그를 보며 올린다.

## 출처

- LightRAG — https://github.com/HKUDS/LightRAG
- LightRAG Core 프로그래밍 가이드(insert·delete·storage) — https://github.com/HKUDS/LightRAG/blob/main/docs/ProgramingWithCore.md
- LightRAG API Server·WebUI — https://github.com/HKUDS/LightRAG/blob/main/docs/LightRAG-API-Server.md
- Neo4j docs — https://neo4j.com/docs/

## 다음 토픽

→ [Phase 4를 닫고 Phase 5로 — Taxonomy · Controlled Vocabulary · Ontology](../../phase-05-ontology-semantic-layer/01-taxonomy-vocabulary-ontology/lesson.md)
