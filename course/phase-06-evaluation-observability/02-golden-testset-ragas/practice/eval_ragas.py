# eval_ragas.py — Ragas(LLM 기반)로 RAG 파이프라인 출력을 평가한다.
#
# 하는 일:
#   1) golden_seed.jsonl(사람이 만든 소형 golden set)을 읽는다.
#   2) 각 질문에 대해 (question, answer, contexts, reference) 4요소를
#      EvaluationDataset 으로 만든다.
#   3) Ragas 지표 4개로 evaluate() 를 호출한다:
#        context_recall / context_precision  → 토픽 01 피라미드의 Retrieval 층
#        faithfulness   / answer_relevancy   → Generation 층
#      즉 01 의 '규칙 기반' recall/precision 을 여기서 'LLM 기반' 지표로 대체·보강한다.
#   4) 끝으로 graph_metrics.py 의 그래프 특화 지표를 얹어 한 장의 카드로 합친다.
#
# ── 전제(비용/키) ──────────────────────────────────────────────────────────
#   실제 평가(--real)는 LLM/임베딩 API 를 호출한다 → 과금된다.
#     필요 키: ANTHROPIC_API_KEY(평가자 LLM), VOYAGE_API_KEY(임베딩).
#   키가 없거나 구조만 보고 싶으면 기본 모드(mock)로 돌린다 — API 호출 0, 과금 0.
#     mock 은 EvaluationDataset 구성까지는 '진짜'로 하고, evaluate() 대신
#     결정적(deterministic) 스텁 점수를 채워 흐름을 보여준다.
#
#   비용 최소화 분기: Claude/VoyageAI 대신 Ollama + bge-m3 로 바꿔도 파이프라인은
#   동일하다. build_evaluator() 안의 주석 블록 참고.
#
# 실행:
#   python eval_ragas.py               # mock (기본, 키/과금 불필요)
#   python eval_ragas.py --real        # 실제 Ragas evaluate (키·과금 필요)

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import graph_metrics as G

SEED_PATH = Path(__file__).parent / "golden_seed.jsonl"


# ---------------------------------------------------------------------------
# 0) golden set 로딩 + RAG 파이프라인 stub
# ---------------------------------------------------------------------------

def load_golden(path: Path = SEED_PATH) -> list[dict]:
    """golden_seed.jsonl 을 dict 리스트로 읽는다."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# 실제로는 여기서 Phase 4 GraphRAG(LightRAG)를 호출해 답과 컨텍스트를 받는다.
#   answer, contexts = lightrag.query(question, mode="mix")
# 이 실습은 평가 파이프라인 자체가 목적이라, 답/컨텍스트를 golden 근거로 흉내낸다.
# contexts 는 chunk 텍스트여야 Ragas 가 제대로 잰다 → 여기선 chunk id 를 텍스트처럼 쓴다.
def run_pipeline(item: dict) -> dict:
    """(question, answer, contexts, reference) 4요소 샘플을 만든다."""
    return {
        "user_input": item["question"],
        # 파이프라인이 낸 답 — 데모에선 reference 를 그대로 답으로 둔다.
        "response": item["reference"],
        # 검색이 가져온 컨텍스트(랭킹순). 실제로는 GraphRAG 검색 결과 텍스트.
        "retrieved_contexts": list(item["reference_contexts"]),
        # 골든 정답(ground truth).
        "reference": item["reference"],
    }


# ---------------------------------------------------------------------------
# 1) 평가자(LLM/임베딩) 구성 — 실제 모드에서만 쓴다
# ---------------------------------------------------------------------------

def build_evaluator():
    """Ragas 평가에 쓸 LLM/임베딩 래퍼를 만든다(실제 모드 전용).

    반환: (evaluator_llm, evaluator_embeddings)
    상용 API 를 부르므로 import 를 함수 안에 둬서 mock 실행 시 의존을 강제하지 않는다.
    """
    from langchain_anthropic import ChatAnthropic
    from langchain_voyageai import VoyageAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    # 평가자 LLM — Claude. 채점자 역할이므로 temperature 는 0.
    llm = ChatAnthropic(model="claude-sonnet-4-5", temperature=0)
    evaluator_llm = LangchainLLMWrapper(llm)

    # 임베딩 — VoyageAI voyage-3.5 (answer_relevancy 등이 쓴다).
    emb = VoyageAIEmbeddings(model="voyage-3.5")
    evaluator_embeddings = LangchainEmbeddingsWrapper(emb)

    # ── 비용 최소화 분기(Ollama + bge-m3) ──────────────────────────────
    # from langchain_ollama import ChatOllama, OllamaEmbeddings
    # evaluator_llm = LangchainLLMWrapper(ChatOllama(model="llama3.1"))
    # evaluator_embeddings = LangchainEmbeddingsWrapper(
    #     OllamaEmbeddings(model="bge-m3"))
    # ───────────────────────────────────────────────────────────────────

    return evaluator_llm, evaluator_embeddings


# ---------------------------------------------------------------------------
# 2) 실제 Ragas 평가
# ---------------------------------------------------------------------------

def evaluate_real(samples: list[dict]) -> dict[str, float]:
    """신형 Ragas API 로 실제 평가한다(과금 발생)."""
    from ragas import EvaluationDataset, evaluate
    # 소문자 싱글턴 지표를 기본으로 쓴다.
    # (클래스형 대안도 있다: Faithfulness / ResponseRelevancy /
    #  LLMContextPrecisionWithReference / LLMContextRecall)
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    evaluator_llm, evaluator_embeddings = build_evaluator()

    # dict 리스트 → EvaluationDataset. 키는 신형 스키마:
    #   user_input / response / retrieved_contexts / reference
    dataset = EvaluationDataset.from_list(samples)

    result = evaluate(
        dataset=dataset,
        metrics=[
            context_recall,      # Retrieval 층
            context_precision,   # Retrieval 층
            faithfulness,        # Generation 층
            answer_relevancy,    # Generation 층
        ],
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
    )
    # result.to_pandas() 로 케이스별 점수도 볼 수 있다. 여기선 집계값만.
    scores = result._repr_dict if hasattr(result, "_repr_dict") else dict(result)
    return {k: float(v) for k, v in scores.items()}


# ---------------------------------------------------------------------------
# 3) mock 평가 — API 호출 없이 흐름만 검증
# ---------------------------------------------------------------------------

def evaluate_mock(samples: list[dict]) -> dict[str, float]:
    """API 없이 결정적 스텁 점수를 채운다.

    EvaluationDataset 구성까지는 실제와 동일하게 시도하되(설치돼 있으면),
    evaluate() 호출만 건너뛴다. 점수는 데모용 고정값이다 — 실제 품질 아님.
    """
    try:
        from ragas import EvaluationDataset
        _ = EvaluationDataset.from_list(samples)  # 스키마가 맞는지 구성만 확인
        built = "EvaluationDataset 구성 OK"
    except Exception as e:  # ragas 미설치 등
        built = f"EvaluationDataset 구성 생략({type(e).__name__})"
    print(f"[mock] {built} — evaluate() 는 건너뜀(과금 0)")

    # 데모용 고정 점수. 층 매핑을 눈으로 확인하는 게 목적.
    return {
        "context_recall": 0.83,
        "context_precision": 0.71,
        "faithfulness": 0.90,
        "answer_relevancy": 0.88,
    }


# ---------------------------------------------------------------------------
# 4) 그래프 특화 지표 케이스 — golden set 을 그래프 로그와 결합
# ---------------------------------------------------------------------------

def build_graph_cases(golden: list[dict]) -> list[dict]:
    """golden set + (여기선 흉내낸) GraphRAG 검색 로그 → 그래프 케이스.

    실제로는 traversed_edges / graph_connected_contexts / retrieved_entities 가
    Phase 4 GraphRAG 검색 로그에서 온다. 데모에선 golden 라벨을 잘 밟았다고 가정한다.
    """
    cases = []
    for item in golden:
        hops = item.get("hops", 1)
        # 요구 홉만큼 엣지를 밟았다고 가정(GraphRAG 성공 케이스).
        traversed = [("n%d" % i, "n%d" % (i + 1)) for i in range(hops)]
        cases.append({
            "required_hops": hops,
            "traversed_edges": traversed,
            "reference_contexts": item["reference_contexts"],
            "graph_connected_contexts": item["reference_contexts"],
            "gold_entities": item.get("gold_entities", []),
            "retrieved_entities": item.get("gold_entities", []),
        })
    return cases


# ---------------------------------------------------------------------------
# 5) 카드 출력
# ---------------------------------------------------------------------------

LAYER_OF = {
    "context_recall": "Retrieval",
    "context_precision": "Retrieval",
    "faithfulness": "Generation",
    "answer_relevancy": "Generation",
}


def print_card(ragas_scores: dict[str, float],
               graph_scores: dict[str, float]) -> None:
    print("=" * 56)
    print("  Ragas(LLM 기반) + Graph-specific — Scorecard")
    print("=" * 56)
    print("\n[Ragas 지표  → 01 피라미드 층 매핑]")
    for name, value in ragas_scores.items():
        layer = LAYER_OF.get(name, "?")
        print(f"  {name:<20} {value:6.3f}   ({layer})")
    print("\n[Graph-specific 지표  → Ragas 로 안 잡히는 그래프 축]")
    for name, value in graph_scores.items():
        print(f"  {name:<26} {value:6.3f}")
    print("\n" + "=" * 56)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ragas + 그래프 특화 평가")
    parser.add_argument("--real", action="store_true",
                        help="실제 Ragas evaluate 호출(키·과금 필요). 기본은 mock")
    args = parser.parse_args()

    golden = load_golden()
    samples = [run_pipeline(item) for item in golden]

    if args.real:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY 가 없다. mock 으로 돌리거나 키를 넣어라.")
        ragas_scores = evaluate_real(samples)
    else:
        ragas_scores = evaluate_mock(samples)

    graph_scores = G.score_graph_cases(build_graph_cases(golden))
    print_card(ragas_scores, graph_scores)


if __name__ == "__main__":
    main()
