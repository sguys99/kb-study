# 4.4 Labs — Vector + Graph Fusion 핸즈온

Vector 후보(Phase 1 하이브리드)와 Graph 후보(4.2 Local·Path / 4.3 Community)를 RRF 로 융합하고, 재순위화한 뒤, 토큰 예산 안에 패킹하는 파이프라인을 단계별로 돌린다.

핵심 파이프라인은 **키 없이, 외부 패키지 없이** 끝까지 돈다(동봉 `sample_candidates.json` + 표준 라이브러리). 재순위화만 백엔드를 쓰는데 그것도 자동 폴백한다. 두 경로를 다 안내한다.

- **비용 0 경로** — 아무 키 없이. reranker 는 `identity` 폴백(또는 로컬 `bge-reranker-v2-m3`), 토큰은 `char/4` 근사.
- **상용 경로** — `VOYAGE_API_KEY` + `voyageai` 로 `rerank-2.5`, `tiktoken` 으로 정확 토큰 카운트.

> 작업 폴더는 `practice/` 다. 아래 명령은 모두 `practice/` 에서 실행한다.
> `python` 명령이 없으면 `python3` 로 바꿔 실행한다.

---

## 0단계 — 설치 (선택)

기본 파이프라인은 설치 없이 돈다. 정확도를 높이고 싶을 때만 선택 패키지를 깐다.

```bash
cd practice
pip install -r requirements.txt   # 기본은 주석 처리돼 있어 아무것도 안 깐다
```

비용 0 로컬 reranker 나 정확 토큰 카운트를 켜려면 `requirements.txt` 의 해당 줄 주석을 풀고 다시 설치한다.

```bash
# (선택) 정확 토큰 카운트
pip install "tiktoken>=0.7"
# (선택) 로컬 무료 reranker
pip install "sentence-transformers>=3.0"
# (선택) 상용 reranker
pip install "voyageai>=0.3"
export VOYAGE_API_KEY=...        # 키는 환경변수로만. 코드에 박지 않는다.
```

**예상 출력** (기본, 아무것도 안 깔림)

```
Successfully installed   ... (아무 패키지도 설치되지 않거나, 이미 충족됨)
```

---

## 1단계 — 샘플 후보 확인

앞 토픽 산출물을 모사한 후보 풀을 공통 스키마로 로드해 본다. Vector 5개 + Graph 5개.

```bash
python candidates.py
```

**예상 출력**

```
[질문] Neo4j 와 RAG 는 어떻게 연결되며, LightRAG 는 그 사이에서 무슨 역할을 하나?
[후보 풀] 총 10개 (vector 5, graph 5)

   v1 [vector] score= 0.83  LightRAG 는 그래프 기반 RAG 프레임워크로, 검색 단계에서 벡터 인덱스와 …
   ...
   g1 [ graph] score= 3.00  [Path] Neo4j -[USES]- LightRAG -[IMPLEMENTS]- GraphRAG -[EX…
   g4 [ graph] score= 8.00  [Community] 커뮤니티 0(검색 기법): RAG·GraphRAG·LightRAG·multi-hop·…
   ...
[다음] python fuse.py 로 스케일 다른 점수를 RRF 로 융합한다.
```

`g4` 의 score 8.00 과 `v1` 의 0.83 을 보라. 스케일이 다르다. 그냥 더하면 안 되는 이유다.

---

## 2단계 — RRF 융합 (전후 순위 비교)

출처별로 따로 세운 순위(융합 전)와, 둘을 한 줄로 합친 순위(융합 후)를 같이 출력한다.

```bash
python fuse.py
```

**예상 출력** (발췌)

```
[융합 전 · vector-only 순위]
  1. v1 (score=0.83) ...
  ...
[융합 전 · graph-only 순위]
  1. g4 (score=8.00) ...
  3. g1 (score=3.00) [Path] Neo4j -[USES]- LightRAG -[IMPLEMENTS]- Gra...
  ...
[융합 후 · RRF(k=60)] 한 줄로 합쳐진 순위:
   1. v1 [vector] fused=0.0164  ...
   2. g4 [ graph] fused=0.0164  ...
   3. v2 [vector] fused=0.0161  ...
   4. g5 [ graph] fused=0.0161  ...
   5. v3 [vector] fused=0.0159  ...
   6. g1 [ graph] fused=0.0159  [Path] Neo4j -[USES]- LightRAG -[IMPLEMENTS]- G...
   ...
[다음] python rerank.py 로 융합 상위 후보를 질문-문서 쌍으로 다시 점수 매긴다.
```

융합 순위가 vector·graph 를 번갈아 끼운다. Vector-only 에는 아예 없던 멀티홉 경로 `g1` 이 6위로 합류한다.

정규화 가중합과 비교하려면 `--minmax` 를 준다.

```bash
python fuse.py --minmax
```

**예상 출력** (발췌 — 가중치를 손으로 정해야 하는 방식)

```
[융합 후 · min-max 가중합(alpha=0.5)] 한 줄로 합쳐진 순위:
   1. v1 [vector] fused=...
   ...
```

---

## 3단계 — 재순위화

### 3-A. 비용 0 경로 (키 없음)

키도 로컬 reranker 도 없으면 `identity` 폴백으로 융합 점수를 그대로 쓴다. 파이프라인 모양은 동일하다.

```bash
python rerank.py
```

**예상 출력**

```
[reranker 백엔드] identity  (VOYAGE_API_KEY 미설정/패키지 없음 → 폴백)
[질문] Neo4j 와 RAG 는 어떻게 연결되며, LightRAG 는 그 사이에서 무슨 역할을 하나?

[재순위 결과] 질문-문서 쌍 점수순:
   1. v1 [vector] rerank=0.0164  ...
   2. g4 [ graph] rerank=0.0164  ...
   ...
[다음] python token_budget.py 로 재순위 상위부터 토큰 예산 안에 담는다.
```

로컬 무료 reranker 를 깔았다면(`sentence-transformers`) 백엔드가 `local` 로 잡히고, cross-encoder 가 질문-문서 쌍을 실제로 보고 점수를 다시 매긴다.

```bash
python rerank.py --backend local
```

**예상 출력** (점수 값은 모델이 정함 — 표면이 닮은 후보가 위로)

```
[reranker 백엔드] local
[재순위 결과] 질문-문서 쌍 점수순:
   1. g1 [ graph] rerank=0.87   [Path] Neo4j -[USES]- LightRAG ...
   2. v1 [vector] rerank=0.81   ...
   ...
```

> 첫 실행 시 `bge-reranker-v2-m3` 모델(수백 MB)을 내려받는다. 이후로는 캐시에서 로드한다.

### 3-B. 상용 경로 (VoyageAI)

`VOYAGE_API_KEY` 가 있고 `voyageai` 가 깔려 있으면 자동으로 `rerank-2.5` 를 부른다.

```bash
export VOYAGE_API_KEY=...
python rerank.py
```

**예상 출력**

```
[reranker 백엔드] voyage
[재순위 결과] 질문-문서 쌍 점수순:
   1. g1 [ graph] rerank=0.93   [Path] Neo4j -[USES]- LightRAG ...
   2. v1 [vector] rerank=0.88   ...
   ...
```

---

## 4단계 — 토큰 예산 패킹

재순위 상위부터 예산이 찰 때까지 담는다. 예산 512 와 1024 를 비교해 본다.

```bash
python token_budget.py 512
```

**예상 출력**

```
[질문] Neo4j 와 RAG 는 어떻게 연결되며, LightRAG 는 그 사이에서 무슨 역할을 하나?
[예산] 512 토큰  →  담긴 후보 6개, 사용 161 토큰

[패킹된 컨텍스트]
    [v1·vector:L120-138] score=0.0164 tok= 26  LightRAG 는 그래프 기반 RAG 프레임워크로 ...
    [g4·graph:community] score=0.0164 tok= 33  [Community] 커뮤니티 0(검색 기법): ...
      [v2·vector:L40-55] score=0.0161 tok= 22  RAG(Retrieval-Augmented Generation)는 ...
    [g5·graph:community] score=0.0161 tok= 29  [Community] 커뮤니티 2(평가·관측): ...
     [v3·vector:L88-101] score=0.0159 tok= 18  RAG 는 의미적으로 가까운 청크를 잘 찾지만 ...
         [g1·graph:path] score=0.0159 tok= 33  [Path] Neo4j -[USES]- LightRAG ...
[렌더된 근거 블록 미리보기]
[v1·vector:L120-138] LightRAG 는 그래프 기반 RAG 프레임워크로 ...
 ...
```

후보 10개 중 6개만 담겼다. `per_source_cap=3` 이라 vector 3 · graph 3 으로 잘렸다(다양성 가드). 멀티홉 경로 `g1` 이 예산 안에 들어온 것을 확인한다.

```bash
python token_budget.py 1024
```

**예상 출력** — 예산을 키워도 결과가 같다. 토큰이 남아도 다양성 가드가 출처 편식을 막기 때문이다.

```
[예산] 1024 토큰  →  담긴 후보 6개, 사용 161 토큰
...
```

> 정확 토큰 카운트를 켜려면 `tiktoken` 을 깐다. 그러면 `tok=` 값이 char/4 근사 대신 실제 토큰 수로 바뀐다(후보 개수는 보통 동일).

---

## 5단계 — 엔드투엔드 파이프라인

`candidates → fuse → rerank → pack` 을 한 번에 돌린다. 이 토픽의 산출물(융합 검색기 진입점)이다.

```bash
python fusion_pipeline.py --budget 512
```

**예상 출력** (발췌)

```
[질문] Neo4j 와 RAG 는 어떻게 연결되며, LightRAG 는 그 사이에서 무슨 역할을 하나?
[reranker 백엔드] identity

[1) RRF 융합 순위]
   1. v1 [vector] 0.0164
   2. g4 [ graph] 0.0164
   ...
   6. g1 [ graph] 0.0159

[2) 재순위 순위]
   ...

[3) 패킹 — 예산 512 토큰, 사용 161 토큰, 후보 6개]
    [v1·vector:L120-138] tok= 26  ...
    [g1·graph:path]      tok= 33  [Path] Neo4j -[USES]- LightRAG ...

[4) LLM 에 줄 근거 블록]
[v1·vector:L120-138] LightRAG 는 그래프 기반 RAG 프레임워크로 ...
[g1·graph:path] [Path] Neo4j -[USES]- LightRAG -[IMPLEMENTS]- GraphRAG -[EXTENDS]- RAG (3홉 경로). ...
```

`--budget`·`--backend` 로 예산과 reranker 백엔드를 바꿔 가며 실험한다.

```bash
python fusion_pipeline.py --budget 256 --backend local
```

---

## 검증 체크리스트 (완료 기준 대조)

- [ ] `fuse.py` 융합 후 순위에 Vector-only 에는 없던 그래프 후보(`g1` Path)가 끼어든다.
- [ ] `token_budget.py 512` 결과에 `g1·graph:path` 가 예산 안으로 들어온다(멀티홉 근거 포함).
- [ ] 다양성 가드로 vector·graph 가 한쪽으로 쏠리지 않는다(`per_source_cap` 적용).
- [ ] `fusion_pipeline.py` 가 키 없이(`identity` 폴백) 끝까지 돌아 근거 블록 + 인용 메타를 출력한다.

> 실제 Graph 후보는 4.2 의 `LocalPathRetriever`·4.3 의 `GlobalRetriever` 출력을, Vector 후보는 Phase 1/06 하이브리드 검색기 출력을 `Candidate` 스키마로 감싸 `load_pool` 자리에 넣으면 된다. 이 랩은 그 출력을 `sample_candidates.json` 으로 모사했다.
