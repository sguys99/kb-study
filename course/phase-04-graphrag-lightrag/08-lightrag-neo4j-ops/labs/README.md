# Labs — LightRAG + Neo4j 운영 (증분·삭제·캐시·동시성)

07에서 파일 기반으로 한 번 인덱싱했다면, 여기서는 그래프 스토리지를 Neo4j로 띄워
운영한다. 증분 적재, 삭제, 캐시, 동시성을 차례로 손으로 확인한다.

> 모든 명령은 `practice/` 안에서 실행한다.
> 예상 출력의 구체적인 수치(노드 수 등)는 LLM·코퍼스에 따라 다르다. **방향(증가/감소)**과
> **상태 전이(processed +1 등)**가 예상대로면 통과다.

## 0. 준비

```bash
cd practice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ANTHROPIC_API_KEY · VOYAGE_API_KEY · NEO4J_PASSWORD 채우기
```

`.env`의 `NEO4J_PASSWORD`와 `docker-compose.yml`의 `NEO4J_AUTH` 비밀번호를 **같은 값**으로 맞춘다.
비용이 부담되면 `.env`의 OLLAMA 블록을 켜고 `BACKEND=ollama`로 둔다(키 불필요).

---

## 1. Neo4j + LightRAG 기동 · 헬스체크

```bash
docker compose up -d
docker compose ps
```

예상 출력(요지):

```
NAME       IMAGE                          STATUS                   PORTS
neo4j      neo4j:5.26                     Up (healthy)             0.0.0.0:7474->7474, 0.0.0.0:7687->7687
lightrag   ghcr.io/hkuds/lightrag:latest  Up (healthy)             0.0.0.0:9621->9621
```

Neo4j가 응답하는지 확인:

```bash
docker compose exec neo4j cypher-shell -u neo4j -p please-change-me "RETURN 1 AS ok;"
```

```
+----+
| ok |
+----+
| 1  |
+----+
```

LightRAG API 헬스체크:

```bash
curl -s http://localhost:9621/health
```

```json
{"status":"healthy","working_dir":"/app/data/rag_storage", ...}
```

브라우저로 `http://localhost:7474`(Neo4j Browser)와 `http://localhost:9621/webui`(LightRAG WebUI)도 열어 둔다.
이 시점의 그래프는 비어 있다.

```cypher
MATCH (n) RETURN count(n) AS nodes;
// nodes = 0
```

---

## 2. 07 코퍼스를 Neo4j 백엔드로 적재

`index_neo4j.py`는 07의 `index_corpus.py`와 똑같지만 `graph_storage="Neo4JStorage"` 한 줄이 다르다.
그래프만 Neo4j로 가고, 임베딩·문서정보·상태는 `rag_storage`(파일)에 남는다.

```bash
python index_neo4j.py
```

예상 출력:

```
[backend] anthropic   [graph_storage] Neo4JStorage
[working_dir] /.../rag_storage  (KV/Vector/DocStatus)   [corpus] ./corpus
  인덱싱: 01-lightrag.md  (612 chars)
  인덱싱: 02-neo4j-rag.md  (...)
  인덱싱: 03-graphrag-research.md  (...)
  인덱싱: 04-incremental-and-storage.md  (...)
[완료] 문서 4건 인덱싱.
       그래프 → Neo4j  /  KV·Vector·DocStatus → /.../rag_storage
```

> 04까지 한 번에 들어간다. 3~4 단계에서 04만 따로 증분/삭제하려면, 먼저 04를
> `corpus/`에서 잠시 빼고 이 단계를 돌린 뒤 되돌려 놓는다. (아래 3단계 주석 참고)

Neo4j Browser에서 노드가 생겼는지 확인:

```cypher
MATCH (n) RETURN count(n) AS nodes;
// 예: nodes = 47  (코퍼스·LLM 에 따라 다름)
MATCH ()-[r]->() RETURN count(r) AS rels;
// 예: rels = 63
```

그래프 모양을 눈으로 보려면:

```cypher
MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50;
```

`rag_storage` 폴더에는 벡터·DocStatus 파일이 보인다(그래프 파일은 없다 — Neo4j로 갔으니까).

```bash
ls rag_storage
# vdb_chunks.json  vdb_entities.json  vdb_relationships.json  kv_store_*.json  doc_status*.json ...
# (graph_chunk_entity_relation.graphml 같은 그래프 파일은 없다)
```

---

## 3. 04 문서 증분 적재 (재인덱싱 없음)

> 이 단계를 제대로 보려면 2단계에서 04를 빼고 01~03만 적재했어야 한다.
> 04까지 이미 들어갔다면, `index_neo4j.py`는 04를 doc id로 스킵하므로 노드가 안 늘어난다.
> 처음부터 다시 보려면 4단계의 삭제로 04를 지운 뒤 이 단계를 돌려도 된다.

```bash
python incremental_insert.py
```

예상 출력:

```
[적재 전] Neo4j {'nodes': 34, 'relationships': 41}   DocStatus {'processed': 3, ...}
[증분] 04-incremental-and-storage.md (980 chars) 만 ainsert (01~03 은 doc id 로 스킵)
[적재 후] Neo4j {'nodes': 47, 'relationships': 63}   DocStatus {'processed': 4, ...}

[Neo4j 그래프] 전후 비교
  nodes                  34 ->       47  (+13)
  relationships          41 ->       63  (+22)

[DocStatus] 전후 비교
  processed               3 ->        4  (+1)

[읽는 법] 노드/관계가 늘면 04 의 새 엔티티·관계가 들어간 것이다. processed 가 +1 ...
```

`processed`가 `+1`이고 노드/관계가 늘면, 전체를 다시 추출하지 않고 04만 그래프에 이어 붙은 것이다.

---

## 4. 04 문서 삭제 (연결 엔티티/관계 정리)

```bash
python delete_ops.py
```

예상 출력:

```
[삭제 전] Neo4j {'nodes': 47, 'relationships': 63}   DocStatus {'processed': 4, ...}
[삭제] doc_id=doc-9f3a...  (await adelete_by_doc_id — async 전용)
[삭제 후] Neo4j {'nodes': 36, 'relationships': 45}   DocStatus {'processed': 3, ...}

[Neo4j 그래프] 전후 비교
  nodes                  47 ->       36  (-11)
  relationships          63 ->       45  (-18)

[DocStatus] 전후 비교
  processed               4 ->        3  (-1)

[읽는 법] 줄어든 노드/관계 = 04 에서만 나온 고유 엔티티/관계. 01~03 과 공유된 ...
```

핵심은 줄어든 폭이 적재 때 늘어난 폭보다 **작다**는 점이다(`-11` < `+13`).
04와 01~03이 공유하는 엔티티(예: LightRAG, Neo4j, 지식그래프)는 다른 문서가 아직
참조하므로 남고, 04에서만 나온 엔티티만 정리된다.

> `adelete_by_doc_id`는 async 전용이다. 동기 `rag.delete(...)`로 부르면 안 된다 — 그런 API는 없다.

Neo4j Browser에서 공유 엔티티가 살아남았는지 확인:

```cypher
MATCH (n) WHERE n.entity_id CONTAINS 'Neo4j' RETURN n LIMIT 5;
// 04 를 지워도 02 가 참조하므로 남아 있다
```

---

## 5. 캐시 확인 · 동시성 조절

### 캐시

방금 지운 04를 다시 증분 적재해 본다.

```bash
python incremental_insert.py
```

로그에서 캐시 적중을 확인한다. 추출 단계 캐시가 켜져 있으면(`ENABLE_LLM_CACHE_FOR_EXTRACT=true`)
같은 청크 재추출에서 LLM 호출이 빠진다.

```
INFO: ... cache hit ... (entity extract)   # 추출 캐시 적중 — LLM 호출 스킵
```

같은 질문을 두 번 던지면(질의 캐시) 두 번째는 LLM 호출 없이 즉답한다.

```bash
# WebUI 또는 curl 로 같은 질문을 두 번
curl -s http://localhost:9621/query -H 'Content-Type: application/json' \
  -d '{"query":"LightRAG 의 스토리지 4종은?","mode":"mix"}' >/dev/null
curl -s http://localhost:9621/query -H 'Content-Type: application/json' \
  -d '{"query":"LightRAG 의 스토리지 4종은?","mode":"mix"}'   # 두 번째는 캐시로 빠르게
```

### 동시성

레이트리밋이나 Neo4j 락 충돌이 보이면 `.env`의 동시성을 낮춘다(낮게 시작해 올린다).

```bash
# .env
MAX_ASYNC_LLM=8           # 동시 LLM 호출 상한
MAX_PARALLEL_INSERT=3     # 동시 인덱싱 문서 수
EMBEDDING_FUNC_MAX_ASYNC=16
EMBEDDING_BATCH_NUM=32
```

바꾼 뒤 LightRAG를 재기동한다.

```bash
docker compose restart lightrag
```

> 삭제 같은 파괴적 연산은 이 값들과 무관하게 직렬화된다. 동시성을 올려도 삭제 중에는
> 새 작업이 끼어들지 못한다(그래프 일관성 보장).

---

## 정리

```bash
docker compose down            # 컨테이너만 내림(neo4j/data 볼륨은 남음)
# docker compose down -v       # 그래프까지 완전 삭제하려면 -v
```

완료 기준: 그래프 스토리지를 Neo4j로 띄워 07 코퍼스를 적재한 뒤, 04 문서 1건을 증분 추가하면
재인덱싱 없이 Neo4j 노드/엔티티가 늘고, `adelete_by_doc_id`로 그 문서를 지우면 연결 엔티티/관계가
정리(공유 엔티티는 보존)되면 완료.
