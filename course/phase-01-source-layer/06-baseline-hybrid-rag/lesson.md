# 1.6 Baseline Hybrid RAG (기준선)

> **Phase 1 · 토픽 06** · 05가 만든 `chunks.jsonl`을 Vector + BM25로 검색하고, 인용 붙은 답을 만들고, Golden Question 10개로 기준선 점수를 측정한다. 이 점수가 Phase 4 GraphRAG와의 A/B 기준이다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Vector(Dense)와 BM25(Sparse) 검색기를 각각 구성하고, RRF로 둘의 순위를 융합한 하이브리드 검색기를 만든다.
- 검색된 청크로 인용(Citation) 답변을 구성해, 각 인용에 05의 chunk_id·source_id·version·char offset을 그대로 달아 04 프로비넌스 사슬을 잇는다.
- Golden Question 10개로 Hit@k·MRR·Recall@k·인용 정확도를 측정하고, 기준선 점수를 `baseline_scores.json`에 영속화한다.

**완료 기준**: `python eval_baseline.py`가 Golden Question 10개를 채점해 기준선 점수표를 찍고, 인용 chunk_id가 붙은 답변이 나오며, `out/baseline_scores.json`이 안정 스키마로 저장되면 완료.

---

## 1. 왜 필요한가 — 기준선이 없으면 개선을 증명할 수 없다

05까지 코퍼스는 검색 가능한 청크가 됐다. `chunks.jsonl` 한 줄이 한 청크고, 각 청크는 04 계약(stable id·version·char offset)을 물고 있다. 이제 검색을 붙일 차례다.

그런데 여기서 멈추면 안 된다. 이 과정의 목표는 GraphRAG가 평범한 RAG보다 낫다는 걸 **증명**하는 거다. 증명하려면 비교 대상이 있어야 한다. "GraphRAG 좋아졌어요"는 측정 없이는 그냥 느낌이다. Phase 4에서 GraphRAG를 켰을 때 얼마나 좋아졌는지 말하려면, 켜기 전 점수가 박제돼 있어야 한다.

그 박제가 이 토픽이다. 흔한 RAG 검색기를 정직하게 만들고, 고정된 질문 10개로 점수를 재서 파일에 남긴다. 이게 기준선(Baseline)이다. 이후 Phase 4·6·7의 모든 개선은 이 숫자와 비교된다.

한 가지 더. 기준선은 일부러 멀티홉 질문이 섞이게 짠다. 한 문서로 답이 안 끝나고 둘 이상을 이어야 하는 질문에서 평범한 Vector 검색이 어떻게 무너지는지를 점수로 드러내려는 거다. 그 빈틈이 Phase 4 GraphRAG가 메울 자리다.

## 2. 왜 Hybrid인가 — Dense와 Sparse는 서로 다른 걸 놓친다

Dense 검색은 임베딩으로 의미 유사도를 본다. "임베딩 기반 의미 검색"이라 물으면 "벡터로 텍스트의 뜻을 담는다"는 청크를 단어가 안 겹쳐도 잘 찾는다. 대신 약점이 있다. `RRF`, `CRAG`, `voyage-3.5` 같은 정확한 약어·고유명사·모델명은 의미 공간에서 흐릿해져 놓치곤 한다.

BM25는 반대다. 단어 빈도와 문서 길이로 점수를 매기는 Sparse 검색이라, 질의에 나온 토큰이 청크에 그대로 있는지를 본다. 약어·고유명사에 강하다. 대신 동의어나 의역은 못 잡는다. "corrective 검색 평가"라고 물어야 CRAG 청크를 찾지, "틀린 검색을 고치는 법"이라 물으면 토큰이 안 겹쳐 놓친다.

둘의 약점이 정확히 엇갈린다. 그래서 합친다. 이게 하이브리드 검색(Hybrid Search)이다.

05가 깔아둔 게 여기서 빛난다. 검색 결과로 받은 chunk_id 하나로 source_id·version·char offset을 즉시 끌어올 수 있다. 그래서 답변에 "이 주장은 src-04-graphrag-ms 문서 v1@xxxx의 [120:340] 구간에서 나왔다"를 코드로 붙인다. 인용이 가능한 건 04·05가 깔아둔 계약 덕이다.

## 3. 실습 — BM25 · Vector · RRF · 인용 · 평가

### BM25 (Sparse)

`rank-bm25`로 색인한다. 핵심은 토크나이저다. 한국어와 영문 약어가 섞인 코퍼스라, 영문·모델명은 통째로 보존하고 한글은 글자 단위로 끊는다. 05 `estimate_tokens`의 'CJK 글자 + 영문 단어' 결을 그대로 따른다.

```python
# practice/bm25_index.py 의 핵심
_ALNUM_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")  # voyage-3.5, GraphRAG 통째로
_CJK_RE = re.compile(r"[가-힣...]")                             # 한글은 글자 단위

def tokenize(text: str) -> list[str]:
    tokens = [m.group().lower() for m in _ALNUM_RE.finditer(text)]
    tokens.extend(_CJK_RE.findall(text))
    return tokens
```

### Vector (Dense) — 비용 0 폴백 내장

기본은 VoyageAI `voyage-3.5`다. **`VOYAGE_API_KEY`가 없으면 결정론적 해시 임베딩으로 자동 폴백**한다. 순수 표준 라이브러리라 네트워크도 키도 0이라, labs 전체가 키 없이 끝까지 돈다. 단, 해시 임베딩은 의미를 거의 못 잡는다. 점수가 낮게 나와도 그건 데모용이지 실측이 아니다.

```python
# practice/vector_index.py 의 핵심
self.backend = "voyage" if os.environ.get("VOYAGE_API_KEY") else "hash-fallback"

def _embed(self, texts, input_type):  # input_type: "document" | "query"
    if self.backend == "voyage":
        res = self._voyage_client().embed(texts, model="voyage-3.5", input_type=input_type)
        return _l2_normalize(np.asarray(res.embeddings, dtype=np.float32))
    return _hash_embed(texts)  # 폴백: hashlib 만. 네트워크 0.
```

VoyageAI는 문서와 질의의 `input_type`을 구분한다. 문서 색인엔 `"document"`, 질의엔 `"query"`를 줘야 검색 품질이 산다. 진짜 로컬 품질이 필요하면 `_embed`만 `bge-m3`(sentence-transformers나 Ollama embeddings)로 갈아끼우면 된다.

### RRF로 융합

Dense는 코사인 0~1, BM25는 0~수십. 스케일이 달라 점수를 직접 더하면 한쪽이 압도한다. 그래서 점수가 아니라 **순위**를 합친다. Reciprocal Rank Fusion이다.

```python
# practice/hybrid_search.py 의 핵심
RRF_K = 60  # 관례값

def _rrf_merge(ranked_lists, k=RRF_K, allow=None):
    fused = {}
    for ranked in ranked_lists:
        for rank, (cid, _score) in enumerate(ranked, start=1):  # 순위만 쓴다
            if allow is not None and cid not in allow:
                continue
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)
```

`k=60`은 정보검색에서 널리 쓰는 평활 상수다. 클수록 상위와 하위 순위의 점수 차가 완만해진다. 한 검색기에만 잡혀도 점수를 받으니, Dense와 Sparse 중 하나라도 잘 잡으면 결과에 살아남는다. `index.json`의 `by_tag`로 후보를 먼저 좁히는 태그 필터도 같은 함수에 끼워 넣었다.

### 인용 답변 — Claude / 추출형 폴백

검색된 청크를 컨텍스트로 넘기면 Claude가 답을 쓰고, 각 주장 끝에 `[chunk_id]`를 단다. **`ANTHROPIC_API_KEY`가 없으면 추출형(extractive) 폴백**으로 전환한다. 상위 청크의 quote를 인용과 묶어 답을 구성한다. LLM 생성이 아니라 근거 발췌지만, 기준선이 보려는 건 인용 정확도라 충분하다.

```python
# practice/answer_with_citations.py 의 핵심
def answer_with_citations(question, chunks):
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _answer_with_claude(question, chunks)   # [chunk_id] 인용 생성
    return _answer_extractive(question, chunks)         # quote + [chunk_id] 발췌
```

어느 경로든 인용 객체에 chunk_id·source_id·version·char_start·char_end·quote를 그대로 담는다. 04 프로비넌스가 답변까지 끊김 없이 이어진다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용을 줄이려면 임베딩을 `bge-m3`(로컬), LLM을 Ollama로 바꿔도 된다. 결과 품질은 떨어질 수 있으나 파이프라인은 동일하게 동작한다.

## 4. 결과 해석

`eval_baseline.py`는 질문 10개를 single-hop과 multi-hop으로 나눠 채점한다.

```
[기준선] embed=voyage  llm=extractive-fallback  k=5  질문=10

  구간         n   Hit@k     MRR  Recall@k    인용정확도
  ---------- --- ------- ------- --------- ---------
  전체        10   0.900   0.800     0.750     0.620
  single-hop   7   1.000   0.950     1.000     0.740
  multi-hop    3   0.667   0.500     0.333     0.330
```

Hit@k는 상위 k 안에 정답 문서가 하나라도 있으면 1이다. MRR은 첫 정답이 얼마나 위에 오는지를, Recall@k는 기대 문서들 중 몇 개를 회수했는지를 본다. 멀티홉 질문은 기대 문서가 둘 이상이라 Recall이 특히 정직하게 떨어진다.

핵심은 마지막 줄이다. single-hop은 점수가 높은데 multi-hop은 Recall@k가 0.333까지 주저앉는다. Vector + BM25는 한 청크와 가장 가까운 걸 찾을 뿐, "Self-RAG와 CRAG를 이어서" 같은 멀티홉 추론을 못 한다. 두 문서를 동시에 끌어와야 하는데 한쪽만 찾고 만다. 이 빈틈이 박제됐다. Phase 4에서 GraphRAG를 켜고 같은 `baseline_scores.json`과 비교하면, 멀티홉 점수가 얼마나 오르는지가 숫자로 나온다.

`meta.embed_backend`가 `hash-fallback`이면 점수는 데모용이다. 진짜 기준선이 필요하면 `VOYAGE_API_KEY`를 켜고 다시 측정한다.

---

## 🚨 자주 하는 실수

1. **BM25 토크나이저가 한국어·약어를 흘린다** — 공백 단순 분할이면 `voyage-3.5`가 `voyage`, `3`, `5`로 쪼개지고 한글은 어절째 뭉텅이로 남아 매칭이 어긋난다. 영문·모델명은 통째로 보존하고 한글은 글자 단위로 끊는 토크나이저를 BM25와 질의에 **똑같이** 써야 한다.
2. **VoyageAI `input_type`을 안 맞춘다** — 문서 색인과 질의에 둘 다 `"document"`(또는 둘 다 `"query"`)를 주면 검색 품질이 떨어진다. 색인은 `"document"`, 질의는 `"query"`다.
3. **폴백 임베딩 점수를 실측으로 착각한다** — `hash-fallback` 백엔드는 의미를 거의 못 잡는 데모용이다. 이 점수를 Phase 4 비교의 기준선으로 박으면 안 된다. 기준선으로 박을 점수는 반드시 `embed_backend=voyage`로 측정한 값이다. 인용에 version·char offset을 빠뜨리는 것도 같은 결의 실수다 — 그러면 04 프로비넌스 사슬이 답변에서 끊긴다.

## 출처

- VoyageAI Embeddings — https://docs.voyageai.com/docs/embeddings
- Pydantic — https://docs.pydantic.dev/
- rank-bm25 (BM25Okapi) — https://github.com/dorianbrown/rank_bm25
- Reciprocal Rank Fusion 원논문(Cormack et al., 2009) — https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf

## 다음 토픽

→ [텍스트 → 그래프 스키마](../../phase-02-knowledge-graph/01-text-to-graph-schema/lesson.md)
