"""같은 문서, 다른 실패 — Vector-only RAG 가 무너지는 4가지를 재현한다.

전제:
  - ANTHROPIC_API_KEY (생성), VOYAGE_API_KEY (임베딩) 환경변수 필요.
  - 비용 대안: .env 에 USE_LOCAL_EMBEDDING=1 이면 임베딩은 로컬 bge-m3 로 분기한다(embeddings.py).
    LLM 도 로컬로 바꾸려면 Ollama 로 client 부분을 교체하면 된다(이 토픽 범위 밖).
  - corpus/ 의 .md 8건을 문서로 쓴다.

실행: python failure_demo.py

이 스크립트는 "정답을 맞히는" 것이 목적이 아니다.
Vector-only RAG 가 멀티홉·관계·전체요약·출처 4가지에서 어떻게 빗나가는지를 눈으로 보는 것이 목적이다.
"""

from __future__ import annotations

import glob
import os
import textwrap

from dotenv import load_dotenv

from embeddings import cosine_topk, embed_documents, embed_query

load_dotenv()

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "corpus")
TOP_K = 3  # Vector-only RAG 가 가져오는 문서 수. 작게 둬서 한계가 잘 드러나게 한다.


def load_corpus() -> list[dict]:
    """corpus/*.md 를 읽어 [{path, name, text}] 로 반환한다."""
    docs = []
    for path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.md"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        docs.append({"path": path, "name": os.path.basename(path), "text": text})
    return docs


def retrieve(query: str, docs: list[dict], doc_matrix) -> list[dict]:
    """질의 임베딩과 코사인 유사도로 상위 TOP_K 문서를 가져온다(순수 벡터 검색)."""
    qv = embed_query(query)
    idxs = cosine_topk(qv, doc_matrix, TOP_K)
    return [docs[i] for i in idxs]


def generate(query: str, retrieved: list[dict]) -> str:
    """검색된 문서만 컨텍스트로 주고 Claude 로 답을 생성한다."""
    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 자동 사용
    context = "\n\n".join(f"[{d['name']}]\n{d['text']}" for d in retrieved)
    prompt = (
        "아래 컨텍스트만 근거로 질문에 답하라. 컨텍스트에 없으면 모른다고 답하라.\n\n"
        f"=== 컨텍스트 ===\n{context}\n\n=== 질문 ===\n{query}"
    )
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# 4가지 실패를 각각 노리는 질문. 단서가 여러 문서에 흩어져 있어 TOP_K=3 벡터검색으로는 부족하다.
FAILURE_QUESTIONS = [
    {
        "kind": "1) 멀티홉 추론",
        "query": (
            "Self-RAG 의 자기평가 아이디어를 검색 품질 보정으로 발전시킨 기법은 "
            "누가 몇 년에 냈는가?"
        ),
        "why": "Self-RAG → CRAG → 저자/연도. 세 문서를 엮어야 하는데 벡터검색은 표면 유사 조각만 가져온다.",
    },
    {
        "kind": "2) 관계 질문",
        "query": "LightRAG 와 Neo4j 는 서로 어떤 관계이며, LightRAG 는 어떤 도구의 비용 문제를 풀려고 나왔는가?",
        "why": "관계는 문서 사이 엣지로 존재한다. 벡터검색은 노드(조각)는 줘도 엣지는 못 준다.",
    },
    {
        "kind": "3) 전체(global) 요약",
        "query": "이 코퍼스 전체를 관통하는 핵심 주제 한 문장과, 등장하는 기법들의 시간 순 흐름을 요약하라.",
        "why": "global 요약은 코퍼스 전체를 봐야 한다. TOP_K=3 조각만 보면 일부만 요약하게 된다.",
    },
    {
        "kind": "4) 출처·근거",
        "query": "위 답의 각 사실이 corpus 의 어느 파일에서 나왔는지 파일명으로 출처를 달아라.",
        "why": "벡터 RAG 는 가져온 조각을 합쳐 생성할 뿐, 문장별 출처 추적(프로비넌스)은 보장하지 못한다.",
    },
]


def main() -> None:
    docs = load_corpus()
    print(f"코퍼스 {len(docs)}건 로드 완료. 임베딩 중...")
    doc_matrix = embed_documents([d["text"] for d in docs])
    print(f"임베딩 완료. 차원={doc_matrix.shape[1]}, TOP_K={TOP_K}\n")

    for q in FAILURE_QUESTIONS:
        print("=" * 72)
        print(f"[{q['kind']}]")
        print(f"Q: {q['query']}")
        retrieved = retrieve(q["query"], docs, doc_matrix)
        print(f"검색된 문서(TOP_K={TOP_K}): {[d['name'] for d in retrieved]}")
        answer = generate(q["query"], retrieved)
        print("A:")
        print(textwrap.indent(answer, "   "))
        print(f"왜 빗나가나: {q['why']}\n")

    print("=" * 72)
    print("4가지 실패를 확인했다면 이 토픽의 동기는 충분하다. healthcheck.py 로 스택을 점검하자.")


if __name__ == "__main__":
    main()
