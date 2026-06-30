# Lab 1.6 — Baseline Hybrid RAG 핸즈온

`practice/`의 코드로 05가 만든 청크를 Vector + BM25로 검색하고, 인용 답변을 만들고, Golden Question 10개로 기준선 점수를 측정한다.

키가 없어도 전 단계가 폴백으로 끝까지 돈다. `VOYAGE_API_KEY`가 없으면 해시 임베딩으로, `ANTHROPIC_API_KEY`가 없으면 추출형 답변으로 자동 전환된다. 해시 임베딩 점수는 데모용이고, 실측 기준선은 `VOYAGE_API_KEY`를 켜고 측정한다.

작업 디렉토리는 `course/phase-01-source-layer/06-baseline-hybrid-rag/practice/`.

아래 예상 출력의 구체적 수치(점수·순위)는 코퍼스·백엔드에 따라 달라진다. 표의 형태와 백엔드 표시, 멀티홉이 single-hop보다 낮게 나오는 경향을 대조하라.

---

## 0. 전제 · 설치

- Python 3.11+
- 선행 산출물이 같은 저장소에 있어야 한다:
  - 05: `course/phase-01-source-layer/05-wiki-parser-chunking/practice/out/chunks.jsonl` + `out/index.json`

```bash
cd course/phase-01-source-layer/06-baseline-hybrid-rag/practice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

키 없이 폴백으로만 돌릴 거면 `voyageai`·`anthropic`은 설치하지 않아도 된다(이미 requirements에 있지만, import는 키가 있을 때만 일어난다).

**예상 출력** (대략):

```
Successfully installed rank-bm25-0.2.2 numpy-1.26.x PyYAML-6.x pydantic-2.x ...
```

## 1. 05 산출물 확인 (없으면 먼저 05 실행)

```bash
python load_chunks.py
```

**예상 출력** (05를 이미 실행한 경우):

```
[load_chunks] 청크 12건 · 문서 8개 · 태그 7종
  태그 목록: ['community-summary', 'embedding', 'foundation', 'framework', 'graph-db', 'rag', 'self-reflection', 'storage']
  첫 청크: src-01-rag#s0-0  (v1@100918bd)  tok=171
    quote: '...'
```

**05를 아직 안 돌렸다면** — 친절한 에러로 멈춘다(05를 먼저 실행하라는 안내):

```
[ERROR] 05 산출물을 찾지 못했다.
        기대 경로: .../05-wiki-parser-chunking/practice/out/chunks.jsonl
        05-wiki-parser-chunking/practice 에서 먼저 다음을 실행하라:
            python run_pipeline.py
        그러면 out/chunks.jsonl 과 out/index.json 이 생긴다.
```

그 경우 05를 먼저 실행한다:

```bash
python ../../05-wiki-parser-chunking/practice/run_pipeline.py
```

## 2. BM25 검색 단독

```bash
python bm25_index.py
```

**예상 출력**:

```
[bm25] query='GraphRAG 커뮤니티 요약'
   4.812  src-04-graphrag-ms#s0-0   '...커뮤니티 요약...'
   2.103  src-08-multihop#s0-0      '...'
   1.547  src-05-lightrag#s0-0      '...'
```

약어·고유명사가 그대로 겹치는 청크가 위로 온다. 점수 0 이하 청크는 떨어진다.

## 3. Vector 검색 단독 — 키 있을 때 vs 폴백

```bash
python vector_index.py
```

**예상 출력 — 폴백** (`VOYAGE_API_KEY` 없음):

```
[vector] backend=hash-fallback  dim=256
   0.214  src-07-embedding#s0-0   '...'
   0.198  src-01-rag#s0-0         '...'
   ...
```

**예상 출력 — 실측** (`VOYAGE_API_KEY` 있음):

```
[vector] backend=voyage  dim=1024
   0.731  src-07-embedding#s0-0   '...임베딩은 텍스트를 벡터로...'
   0.689  src-01-rag#s0-0         '...'
   ...
```

두 경우 모두 끝까지 돈다. 폴백은 차원 256·점수 낮음·의미 약함이고, 실측은 차원 1024·의미 유사도가 또렷하다. 실측 임베딩은 `out/emb_voyage.npy`에 캐시돼 재실행 시 다시 호출하지 않는다.

## 4. Hybrid (RRF) 검색

```bash
python hybrid_search.py
```

**예상 출력**:

```
[hybrid] backend=hash-fallback  query='CRAG 와 Self-RAG 의 차이'

  dense  : ['src-01-rag#s0-0', 'src-07-embedding#s0-0', 'src-03-crag#s0-0']
  sparse : ['src-03-crag#s0-0', 'src-02-self-rag#s0-0', 'src-05-lightrag#s0-0']
  hybrid :
    0.03252  src-03-crag#s0-0        '...corrective...'
    0.01613  src-02-self-rag#s0-0    '...reflection...'
    0.01587  src-01-rag#s0-0         '...'
```

dense와 sparse가 각각 놓친 걸 RRF가 합쳐 끌어올린다. sparse가 약어(CRAG·Self-RAG)를 잡고, dense가 의역을 보태, 융합 결과에 둘 다 살아남는다.

## 5. 인용 답변 1건

```bash
python answer_with_citations.py
```

**예상 출력 — 추출형 폴백** (`ANTHROPIC_API_KEY` 없음):

```
[answer] backend=extractive-fallback

질문 'GraphRAG 는 전역 요약 질문을 어떻게 다루나?' 에 대한 근거 발췌(추출형 폴백):
- ...커뮤니티 단위로 요약을 만들어 전역 질문에 답한다... [src-04-graphrag-ms#s0-0]
- ...멀티홉 질의는 여러 노드를 이어... [src-08-multihop#s0-0]

인용:
  [src-04-graphrag-ms#s0-0]  src-04-graphrag-ms v1@xxxxxxxx  [0:340]
  [src-08-multihop#s0-0]     src-08-multihop v1@xxxxxxxx  [0:210]
```

**키가 있으면** `backend=claude`로 바뀌고, 답이 문장으로 생성되며 각 주장 끝에 `[chunk_id]`가 붙는다. 어느 경로든 인용에 source_id·version·char offset이 그대로 따라붙는 것을 확인하라 — 04 프로비넌스가 답변까지 이어진 증거다.

## 6. 기준선 점수 측정 + 영속화

```bash
python eval_baseline.py
```

**예상 출력**:

```
[기준선] embed=hash-fallback  llm=extractive-fallback  k=5  질문=10

  구간         n   Hit@k     MRR  Recall@k    인용정확도
  ---------- --- ------- ------- --------- ---------
  전체        10   0.700   0.560     0.500     0.480
  single-hop   7   0.857   0.690     0.857     0.620
  multi-hop    3   0.333   0.260     0.167     0.200

  질문별:
    gq01  single-hop   1    1   1.00  ['src-01-rag', ...]
    gq02  single-hop   1    1   1.00  ['src-02-self-rag', ...]
    ...
    gq08  multi-hop    1    2   0.50  ['src-03-crag', 'src-02-self-rag', ...]
    gq09  multi-hop    0    0   0.00  ['src-05-lightrag', ...]
    gq10  multi-hop    0    0   0.00  ['src-01-rag', ...]

  ⚠️ embed_backend=hash-fallback — 해시 임베딩 데모 점수다. 실측이 아니다.
     VOYAGE_API_KEY 를 설정하면 voyage-3.5 실측 점수가 나온다.

  ※ multi-hop 의 점수가 single-hop 보다 낮다 — 이게 Phase 4 GraphRAG 의 동기다.

[완료] 기준선 점수 저장: out/baseline_scores.json
```

마지막 두 줄이 이 토픽의 핵심이다. 멀티홉 질문(gq08~gq10)에서 점수가 주저앉는다. 한 문서로 답이 안 끝나는데 Vector + BM25가 둘을 동시에 못 끌어온다. 이 빈틈이 Phase 4 GraphRAG가 메울 자리다.

## 7. 저장된 기준선 확인

```bash
cat out/baseline_scores.json
```

**예상 출력** (발췌):

```json
{
  "meta": {
    "embed_backend": "hash-fallback",
    "llm_backend": "extractive-fallback",
    "k": 5,
    "n_questions": 10,
    "generated_at": "2026-06-30T12:00:00+00:00"
  },
  "metrics": {
    "n": 10, "hit_at_k": 0.7, "mrr": 0.56, "recall_at_k": 0.5, "citation_precision": 0.48,
    "single_hop": { "n": 7, "hit_at_k": 0.857, "...": "..." },
    "multi_hop":  { "n": 3, "hit_at_k": 0.333, "...": "..." }
  },
  "per_question": [
    { "id": "gq01", "type": "single-hop", "hit": 1, "first_rank": 1, "recall": 1.0, "...": "..." }
  ]
}
```

이 파일이 Phase 4 GraphRAG A/B 비교의 입력이 된다. 실측 기준선을 남기려면 `VOYAGE_API_KEY`(가능하면 `ANTHROPIC_API_KEY`도)를 설정하고 6번을 다시 실행해 덮어쓴다.

---

## 검증 체크리스트

- [ ] `python load_chunks.py`가 청크 건수·태그 목록을 찍는다(05 산출물 로드 확인).
- [ ] BM25·Vector·Hybrid 각각 단독 실행이 결과를 낸다.
- [ ] Vector가 키 유무에 따라 `backend=voyage` 또는 `hash-fallback`으로 자동 전환된다.
- [ ] 인용 답변에 chunk_id·source_id·version·char offset이 붙는다.
- [ ] `eval_baseline.py`가 점수표를 찍고 `out/baseline_scores.json`을 저장한다.
- [ ] multi-hop 점수가 single-hop보다 낮게 나온다(Phase 4 동기).
