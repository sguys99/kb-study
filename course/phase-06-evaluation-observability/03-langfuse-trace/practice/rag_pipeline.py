# rag_pipeline.py — GraphRAG/에이전트 파이프라인을 Langfuse trace 로 계측한다.
#
# 이 토픽에서 배우는 것:
#   한 질문이 들어와 어떤 검색 경로(vector → graph)를 밟고, 어떤 Tool Call
#   (docs_search · graph_query)이 일어났고, 각 스텝의 latency/토큰/cost 가 얼마인지를
#   span 트리로 남긴다. LLM 호출은 generation span 으로 usage_details·cost_details·model 을 기록.
#   끝에서 02 Ragas 점수를 이 trace 에 score 로 붙여 '평가'와 '관측'을 잇는다.
#
# 계측 두 방식(둘 다 보여준다):
#   1) @observe()  — 함수 진입/종료를 자동 span 으로. answer_question() 이 최상위 trace.
#   2) 수동 span   — start_as_current_observation(...) 로 검색 스텝을 중첩 span 으로.
#
# ── 전제(비용/키) ────────────────────────────────────────────────────────────
#   실제 Langfuse 전송: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST 필요.
#     self-host 는 docker-compose.yml 로 서버를 먼저 띄운다(labs/ 참고).
#   실제 LLM 호출(--real-llm): ANTHROPIC_API_KEY 필요 → 과금.
#   키가 없으면? 파이프라인은 그대로 돈다.
#     - 트레이스는 콘솔 트레이서(trace_util.py)로 콘솔에 span 트리·cost·latency 를 찍는다.
#     - LLM 은 결정적(deterministic) 스텁으로 대체(과금 0).
#
#   비용 최소화 분기: Claude 대신 Ollama + bge-m3 로 바꿔도 계측 구조는 동일하다.
#     call_llm() 안의 주석 블록 참고(모델명·usage·cost 만 그 값으로 바꿔 기록).
#
# 실행:
#   python rag_pipeline.py                 # 스텁 LLM + (키 없으면) 콘솔 트레이서
#   python rag_pipeline.py --real-llm      # 실제 Claude 호출(과금)
#   # 실제 Langfuse 전송은 세 LANGFUSE_* 키를 export 한 뒤 위 명령을 그대로 실행

from __future__ import annotations

import argparse
import os
import time

from langfuse import observe  # v3: 함수 자동 계측 데코레이터
from trace_util import get_tracer

# 트레이서는 모듈 로드 시 한 번 결정한다(진짜 Langfuse 또는 콘솔 폴백).
tracer = get_tracer()


# ---------------------------------------------------------------------------
# 0) 아주 작은 코퍼스 스텁 — Phase 1~4 산출물(벡터 인덱스+KG)의 자리표시자.
#    실제 과정에서는 이 자리에 LightRAG/Neo4j 검색이 들어간다. 여기선 계측 흐름에 집중.
# ---------------------------------------------------------------------------
CORPUS = {
    "c2": "From Local to Global(arXiv 2404.16130)은 커뮤니티 요약 기법을 제안한다.",
    "c4": "이 방법은 Leiden 커뮤니티 탐지 알고리즘으로 그래프를 커뮤니티로 나눈다.",
    "c7": "Self-RAG(arXiv 2310.11511)는 검색 여부를 스스로 판단한다.",
}
# 아주 단순한 KG: (엔티티)-[관계]->(엔티티). graph_query 가 1홉 확장에 쓴다.
GRAPH_EDGES = [
    ("From Local to Global", "USES", "Leiden"),
    ("From Local to Global", "PROPOSES", "community summary"),
]


# ---------------------------------------------------------------------------
# 1) Tool Call 스텝 — 각각을 span 으로 남긴다(검색 경로가 트리에 보이게).
# ---------------------------------------------------------------------------
def docs_search(query: str, k: int = 2) -> list[dict]:
    """벡터 검색 자리표시자. Tool Call 하나 = span 하나."""
    with tracer.start_as_current_observation(
        name="docs_search", as_type="tool", input={"query": query, "k": k}
    ) as span:
        time.sleep(0.01)  # 지연을 눈에 보이게 하는 인위적 delay(실제로는 검색 시간)
        # 질의어에 등장하는 단어가 들어간 문서를 점수순으로(스텁 랭킹).
        scored = []
        for cid, text in CORPUS.items():
            hits = sum(1 for w in query.split() if w in text)
            if hits:
                scored.append({"doc_id": cid, "text": text, "score": hits})
        scored.sort(key=lambda d: d["score"], reverse=True)
        hits = scored[:k]
        span.update(output={"hit_ids": [h["doc_id"] for h in hits]},
                    metadata={"path": "vector"})
        return hits


def graph_query(seed_entities: list[str]) -> list[dict]:
    """KG 1홉 확장 자리표시자. vector hit 을 그래프로 넓히는 경로를 span 으로 남긴다."""
    with tracer.start_as_current_observation(
        name="graph_query", as_type="tool", input={"seed_entities": seed_entities}
    ) as span:
        time.sleep(0.01)
        expanded = []
        for (h, rel, t) in GRAPH_EDGES:
            if h in seed_entities or t in seed_entities:
                expanded.append({"head": h, "rel": rel, "tail": t})
        span.update(output={"edges": expanded}, metadata={"path": "graph"})
        return expanded


# ---------------------------------------------------------------------------
# 2) LLM 호출 — generation span 으로 model·usage_details·cost_details 를 기록.
# ---------------------------------------------------------------------------
# 참고용 단가(2024~2025 기준, USD / 1M tokens). 실제 청구는 콘솔에서 확인할 것.
_PRICE = {"claude-3-5-sonnet-latest": {"in": 3.0, "out": 15.0}}


def _cost(model: str, pt: int, ct: int) -> float:
    p = _PRICE.get(model, {"in": 0.0, "out": 0.0})
    return pt / 1_000_000 * p["in"] + ct / 1_000_000 * p["out"]


def call_llm(prompt: str, contexts: list[str], real: bool) -> dict:
    """LLM 답변 생성. generation span 에 토큰·비용·모델을 남긴다."""
    model = "claude-3-5-sonnet-latest"
    with tracer.start_as_current_observation(
        name="generate_answer", as_type="generation", input={"prompt": prompt}
    ) as span:
        if real and os.environ.get("ANTHROPIC_API_KEY"):
            # ── 실제 Claude 호출(과금) ──
            from anthropic import Anthropic

            client = Anthropic()  # ANTHROPIC_API_KEY 를 환경에서 읽는다.
            joined = "\n".join(contexts)
            msg = client.messages.create(
                model=model,
                max_tokens=256,
                messages=[{"role": "user",
                           "content": f"컨텍스트:\n{joined}\n\n질문: {prompt}\n근거만으로 답하라."}],
            )
            answer = msg.content[0].text
            pt = msg.usage.input_tokens
            ct = msg.usage.output_tokens
            # 비용 최소화 분기(Ollama): 위 블록을 로컬 호출로 바꾸고 model="qwen2.5",
            #   cost 는 0.0 으로 기록하면 된다. usage 는 응답에서 받거나 근사한다.
        else:
            # ── 스텁 LLM(과금 0, 결정적) ──
            answer = "커뮤니티 요약은 From Local to Global 이 제안했고 Leiden 알고리즘을 쓴다."
            pt, ct = len(prompt) // 4 + 40, len(answer) // 4  # 대략적 토큰 근사

        cost = _cost(model, pt, ct)
        span.update(
            output=answer,
            model=model,
            usage_details={"prompt_tokens": pt, "completion_tokens": ct,
                           "total_tokens": pt + ct},
            cost_details={"total_cost": cost},
        )
        return {"answer": answer, "prompt_tokens": pt, "completion_tokens": ct, "cost": cost}


# ---------------------------------------------------------------------------
# 3) 검색 단계 — vector hit → graph 확장을 하나의 부모 span 아래 중첩한다.
#    이 부모 span 이 UI 에서 "검색 경로" 한 덩어리로 보인다.
# ---------------------------------------------------------------------------
def retrieve(question: str) -> dict:
    with tracer.start_as_current_observation(
        name="retrieval", as_type="span", input={"question": question}
    ) as span:
        hits = docs_search(question, k=2)                      # 자식 span 1: vector
        seeds = _entities_from_hits(hits)
        edges = graph_query(seeds)                             # 자식 span 2: graph
        contexts = [h["text"] for h in hits] + [
            f"{e['head']} -{e['rel']}-> {e['tail']}" for e in edges
        ]
        span.update(output={"n_contexts": len(contexts),
                            "path": "vector→graph"})
        return {"contexts": contexts, "hit_ids": [h["doc_id"] for h in hits],
                "edges": edges}


def _entities_from_hits(hits: list[dict]) -> list[str]:
    """검색된 문서에서 KG seed 엔티티를 뽑는 자리표시자."""
    ents = set()
    for h in hits:
        for e in ("From Local to Global", "Leiden", "community summary"):
            if e in h["text"]:
                ents.add(e)
    return list(ents)


# ---------------------------------------------------------------------------
# 4) 최상위 trace — @observe() 로 answer_question() 전체가 하나의 trace 가 된다.
# ---------------------------------------------------------------------------
@observe()
def answer_question(question: str, real_llm: bool = False) -> dict:
    tracer.update_current_trace(input={"question": question})

    r = retrieve(question)                                     # 중첩 span 트리
    gen = call_llm(question, r["contexts"], real=real_llm)     # generation span

    result = {"answer": gen["answer"], "contexts": r["contexts"],
              "hit_ids": r["hit_ids"],
              "cost": gen["cost"],
              "tokens": gen["prompt_tokens"] + gen["completion_tokens"]}
    tracer.update_current_trace(output={"answer": result["answer"]})
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-llm", action="store_true",
                    help="실제 Claude 호출(과금). 미지정 시 스텁 LLM.")
    args = ap.parse_args()

    question = "커뮤니티 요약 기법은 어느 논문에서 제안됐고 어떤 그래프 알고리즘을 쓰나?"
    result = answer_question(question, real_llm=args.real_llm)

    # ── 02 Ragas 점수를 이 trace 에 붙인다(평가 ↔ 관측 연결) ──
    #   실제로는 eval_ragas.py 의 출력값을 여기로 넘긴다. 여기선 예시 값.
    tracer.score_current_trace(name="faithfulness", value=0.92,
                               comment="02 Ragas 결과에서 가져옴")
    tracer.score_current_trace(name="context_recall", value=1.0)

    # 스크립트 끝에서 반드시 flush — 안 하면 trace 가 서버로 안 가고 유실된다.
    tracer.flush()

    print("\n== 최종 답변 ==")
    print(result["answer"])
    print(f"(tokens={result['tokens']}, cost=${result['cost']:.6f})")


if __name__ == "__main__":
    main()
