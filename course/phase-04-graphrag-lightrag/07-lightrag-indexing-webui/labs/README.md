# Lab 4.7 — LightRAG 인덱싱 · 5모드 A/B · WebUI 시각화

06에서 개념으로 묶은 5모드를 실제로 돌린다. 러닝 코퍼스를 한 번 인덱싱하고, 같은 골든 질문을 다섯 모드로 던져 비교한 뒤, API 서버를 띄워 그래프와 검색 경로를 WebUI로 본다. 마지막으로 multi-hop·global-summary에서 `naive`(=Phase 1 Baseline) 대비 무엇이 좋아졌는지 판정한다.

전제: Python 3.11+, Docker(WebUI용, 선택), 그리고 키 한 벌.
- 기본 스택: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` (Claude + VoyageAI).
- 비용 0 대안: Ollama 데몬 + `ollama pull qwen2.5` + `ollama pull bge-m3` (키 불필요).

작업 위치:

```bash
cd course/phase-04-graphrag-lightrag/07-lightrag-indexing-webui/practice
```

---

## 0단계 — 설치

```bash
pip install -r requirements.txt
python3 -c "import lightrag; print('lightrag ok')"
```

예상 출력:

```
lightrag ok
```

---

## 1단계 — .env 작성

```bash
cp .env.example .env
# .env 를 열어 키를 채운다. 기본 = BASIC(Claude+Voyage) 블록.
# 비용 0 으로 갈 거면 OLLAMA 블록을 주석 해제하고 BASIC 을 주석 처리.
```

키가 잘 잡혔는지 확인(값은 가린다):

```bash
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print('ANTHROPIC', bool(os.environ.get('ANTHROPIC_API_KEY'))); print('VOYAGE', bool(os.environ.get('VOYAGE_API_KEY')))"
```

예상 출력(기본 스택):

```
ANTHROPIC True
VOYAGE True
```

비용 0 대안을 쓸 경우 키 대신 `BACKEND=ollama` 로 두고 Ollama 데몬이 떠 있으면 된다.

---

## 2단계 — 코퍼스 인덱싱 (ainsert)

`./corpus` 의 샘플 3개를 인덱싱한다. 실제 학습에서는 `CORPUS_DIR` 로 Phase 1 산출물 경로를 가리킨다.

```bash
python3 index_corpus.py
```

예상 출력(요약):

```
[backend] anthropic   [working_dir] ./rag_storage   [corpus] ./corpus
  인덱싱: 01-lightrag.md  (612 chars)
INFO:lightrag:Chunk 1 of 1 extracted 7 entities, 5 relationships
  인덱싱: 02-neo4j-rag.md  (548 chars)
INFO:lightrag:Chunk 1 of 1 extracted 6 entities, 6 relationships
  인덱싱: 03-graphrag-research.md  (701 chars)
INFO:lightrag:Chunk 1 of 1 extracted 9 entities, 8 relationships
[완료] 문서 3건 인덱싱. 저장소: /.../practice/rag_storage
       이제 ab_query_modes.py 로 5모드 A/B 를 돌리거나 WebUI 로 띄운다.
```

확인: `rag_storage/` 가 생기고 그 안에 그래프·벡터 저장 파일이 쌓인다.

```bash
ls rag_storage
```

예상 출력(파일명은 버전에 따라 다를 수 있음):

```
graph_chunk_entity_relation.graphml   kv_store_full_docs.json
vdb_chunks.json                       vdb_entities.json   vdb_relationships.json
kv_store_text_chunks.json             ...
```

엔티티·관계가 추출되고 저장소가 생겼다면 통과. 이 하나의 저장소를 5모드가 공유한다(재인덱싱 불필요).

---

## 3단계 — 5모드 A/B

같은 골든 질문 3개를 `naive/local/global/hybrid/mix` 다섯 모드로 던진다. 인덱싱은 안 다시 하고 질의만 돈다.

```bash
python3 ab_query_modes.py
```

예상 출력(답 본문은 모델·코퍼스에 따라 달라짐 — 모드 간 우열을 본다):

```
=== [simple-fact] VoyageAI의 기본 임베딩 모델 이름은? ===
  [naive ] voyage-3.5 입니다.
  [local ] voyage-3.5 입니다.
  [global] 임베딩 모델로 voyage-3.5 가 언급됩니다.
  [hybrid] voyage-3.5 입니다.
  [mix   ] voyage-3.5 입니다.  <- Core 권장 기본

=== [multi-hop] Neo4j와 RAG는 어떻게 이어지나? ===
  [naive ] 관련 청크만으로는 연결이 흐릿합니다…
  [local ] Neo4j는 멀티홉 경로를 그래프 탐색으로 끌어와 RAG의 약점을 메웁니다…
  [global] 그래프 DB가 검색 기반이 된다는 거시 설명…
  [hybrid] Neo4j가 엔티티 관계를 따라 멀티홉을 잇고 RAG와 연결됩니다…
  [mix   ] Neo4j의 그래프 탐색이 RAG 멀티홉을 보완하며 이어집니다…  <- Core 권장 기본

=== [global-summary] 이 코퍼스의 GraphRAG 연구 흐름을 전체 요약해줘. ===
  [naive ] 일부 청크 기준의 부분 요약…
  [local ] 특정 엔티티 주변 요약에 치우침…
  [global] 추출→커뮤니티 탐지→유형별 검색의 세 줄기로 전체를 조망…
  [hybrid] 전체 흐름 + 엔티티 디테일을 함께…
  [mix   ] 코퍼스 전반을 KG+vector 로 통합 요약…  <- Core 권장 기본

[저장] /.../practice/ab_result.json
[읽는 법] simple-fact는 naive로도 충분한가, multi-hop은 local이, global-summary는 global이 naive(=Phase 1 Baseline)보다 나은가를 본다.
[기본 모드] Core 직접 호출 = mix, WebUI 무prefix = hybrid (반드시 구분)
```

대조 포인트:
- simple-fact: `naive` 도 정답을 낸다(답이 한 청크에 들어 있음).
- multi-hop: `naive` 가 흐려지고 `local/hybrid/mix` 가 관계를 끌어온다.
- global-summary: `naive` 는 부분 요약, `global/mix` 가 전체를 조망한다.

JSON으로도 확인:

```bash
python3 -c "import json; d=json.load(open('ab_result.json')); print(len(d), 'questions x', len(d[0]['answers']), 'modes')"
```

예상 출력:

```
3 questions x 5 modes
```

---

## 4단계 — API 서버 + WebUI 띄우기

Docker로 API 서버를 올린다(`.env` 를 그대로 쓴다).

```bash
docker compose up -d
```

예상 출력:

```
[+] Running 2/2
 ✔ Network practice_default  Created
 ✔ Container lightrag        Started
```

헬스체크:

```bash
curl http://localhost:9621/health
```

예상 출력(요약):

```
{"status":"healthy","working_directory":"...","configuration":{...}}
```

브라우저로 접속:

```
http://localhost:9621/webui
```

WebUI에서 보이는 것:
- 문서 업로드·인덱싱 화면(2단계를 CLI 대신 여기서도 가능).
- 질의창에 질문을 넣고 답·인용을 본다.
- Knowledge Graph 탭에서 엔티티·관계 그래프를 시각적으로 돌려본다. `local` 질의는 엔티티 이웃으로 뻗는 경로가, `global` 질의는 커뮤니티 단위 묶음이 드러난다.

무prefix 기본은 `hybrid` 다. 모드를 강제하려면 질문 앞에 prefix를 붙인다:

```
/local  Neo4j와 RAG는 어떻게 이어지나?
/global 이 코퍼스의 GraphRAG 연구 흐름을 전체 요약해줘.
/mix    Neo4j와 RAG는 어떻게 이어지나?
```

같은 질문이라도 `/local` 과 prefix 없는 질의(=hybrid)의 답·그래프 경로가 다르게 보이면 정상이다. 여기서 06의 함정(Core 기본 mix ↔ API 무prefix hybrid)을 화면으로 확인한다.

정리:

```bash
docker compose down
```

---

## 5단계 — Baseline(naive) 대비 판정

3단계 결과(콘솔/`ab_result.json`)와 4단계 WebUI 화면을 종합해 한 줄로 판정한다.

판정 기준: `naive`(=Phase 1 Baseline)가 simple-fact에서는 멀쩡한데 multi-hop·global-summary에서 답이 흐려지고, 그 자리를 `local/global/mix`가 메우면 KG 도입 값을 한 것이다. `mix`가 type을 가리지 않고 가장 견고하게 나오면 4.5의 Hybrid 결론이 LightRAG 위에서 재현된 것이다.

정밀 채점(정답률 수치)은 Phase 6에서 Ragas로 자동화한다. 07에서는 답·인용·그래프 경로를 눈으로 대조하는 수준으로 충분하다.

---

## 검증 체크리스트

- [ ] 2단계: `index_corpus.py` 가 문서를 인덱싱하고 `rag_storage/` 가 생긴다(엔티티·관계 추출 로그 확인).
- [ ] 3단계: `ab_query_modes.py` 가 3질문 × 5모드 표를 찍고 `ab_result.json` 을 남긴다.
- [ ] 3단계: simple-fact는 `naive` 도 정답, multi-hop·global-summary는 `local/global/mix` 가 더 낫다.
- [ ] 4단계: `curl /health` 가 healthy, `http://localhost:9621/webui` 가 열리고 그래프가 보인다.
- [ ] 4단계: prefix 없는 질의(=hybrid)와 `/local`·`/mix` 질의의 답·경로가 다르게 보인다.
- [ ] 5단계: multi-hop·global-summary에서 `local/global/mix` 가 `naive`(=Baseline)보다 나으면 완료.
