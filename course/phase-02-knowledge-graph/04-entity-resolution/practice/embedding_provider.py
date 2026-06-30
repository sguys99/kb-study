"""embedding_provider.py — 엔티티 이름을 벡터로 바꾼다. 백엔드를 갈아끼운다.

4단계 ER 의 마지막 단계(embedding 병합)는 alias·fuzzy 가 못 잡는 '의미 중복'을
임베딩 코사인 유사도로 잡는다. 임베딩 출처는 세 가지 중 하나를 고른다:

  backend="mock"   기본. 해시 기반 결정적 벡터. 키·네트워크 불필요. labs 가 이걸로 돈다.
  backend="voyage" 상용. VoyageAI voyage-3.5. VOYAGE_API_KEY 필요(선택 의존).
  backend="local"  로컬·무료. BAAI/bge-m3. sentence-transformers 필요(선택 의존).

세 백엔드는 같은 인터페이스다: get_embeddings(texts, backend) -> list[list[float]].
mock 으로 파이프라인을 다 돌려보고, 키가 있으면 voyage 로, 비용이 부담되면 local 로
한 줄만 바꾼다. 2/03 의 mock/anthropic/instructor 백엔드 교체와 같은 철학이다.

⚠️ mock 임베딩은 '의미'를 모른다. 문자열을 결정적 벡터로 바꿀 뿐이다. 그래서 labs 의
embedding 단계는 실제 의미 병합을 시연하지 못한다(같은 표면형이면 같은 벡터, 다르면
거의 직교). 의미 병합의 진짜 효과는 voyage·local 백엔드에서 확인한다. 이 한계는
의도된 것이다 — 키 없이 파이프라인 구조를 먼저 익히게 하려는 것이다.

전제: mock 경로는 표준 라이브러리만 필요(키·패키지 불필요).
의존: voyage → voyageai>=0.3, local → sentence-transformers>=3.
"""

from __future__ import annotations

import hashlib
import math
import os

# mock 벡터 차원. 작게 잡는다 — 결정성·재현성만 필요하고 품질은 따지지 않는다.
_MOCK_DIM = 64


def _mock_embedding(text: str) -> list[float]:
    """해시 기반 결정적 벡터. 같은 입력이면 항상 같은 벡터, 키·네트워크 불필요.

    문자열을 정규화한 뒤 SHA-256 으로 바이트를 뽑아 [-1, 1] 범위 실수로 펼친다.
    L2 정규화해 코사인 유사도가 내적과 같아지게 한다. '의미'는 없다 — 같은 표면형은
    같은 벡터, 다른 표면형은 거의 직교한다. 파이프라인 구조 시연용이다.
    """
    norm = text.strip().lower()
    vec: list[float] = []
    counter = 0
    # 필요한 차원 수만큼 해시 블록을 이어 붙인다.
    while len(vec) < _MOCK_DIM:
        block = hashlib.sha256(f"{norm}#{counter}".encode("utf-8")).digest()
        for b in block:
            vec.append((b / 255.0) * 2.0 - 1.0)  # 0..255 → -1..1
            if len(vec) >= _MOCK_DIM:
                break
        counter += 1
    # L2 정규화.
    length = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / length for x in vec]


def _voyage_embeddings(texts: list[str]) -> list[list[float]]:
    """VoyageAI voyage-3.5 임베딩. VOYAGE_API_KEY 필요. (선택 의존)"""
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "backend='voyage' 인데 VOYAGE_API_KEY 가 없다. "
            "export VOYAGE_API_KEY=... 후 다시 실행하라(또는 backend='mock')."
        )
    try:
        import voyageai  # type: ignore  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 선택 의존
        raise ImportError(
            "voyageai 패키지가 없다. pip install 'voyageai>=0.3' 후 다시 실행하라."
        ) from exc
    client = voyageai.Client(api_key=api_key)
    # input_type='document' 로 엔티티 표면형을 임베딩한다.
    result = client.embed(texts, model="voyage-3.5", input_type="document")
    return [list(v) for v in result.embeddings]


def _local_embeddings(texts: list[str]) -> list[list[float]]:
    """로컬 BAAI/bge-m3 임베딩. sentence-transformers 필요. 비용 0. (선택 의존)"""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 선택 의존
        raise ImportError(
            "sentence-transformers 패키지가 없다. "
            "pip install 'sentence-transformers>=3' 후 다시 실행하라."
        ) from exc
    model = SentenceTransformer("BAAI/bge-m3")
    vecs = model.encode(texts, normalize_embeddings=True)
    return [list(map(float, v)) for v in vecs]


def get_embeddings(texts: list[str], backend: str = "mock") -> list[list[float]]:
    """엔티티 표면형 리스트를 벡터 리스트로 바꾼다. 백엔드만 갈아끼운다.

    반환: texts 와 같은 길이·순서의 list[list[float]]. 모두 L2 정규화돼 있다고 가정한다.
    """
    if not texts:
        return []
    if backend == "mock":
        return [_mock_embedding(t) for t in texts]
    if backend == "voyage":
        return _voyage_embeddings(texts)
    if backend == "local":
        return _local_embeddings(texts)
    raise ValueError(f"알 수 없는 backend: {backend!r} (mock|voyage|local)")


def cosine(a: list[float], b: list[float]) -> float:
    """코사인 유사도. 입력이 L2 정규화돼 있으면 내적과 같다(안전하게 다시 정규화)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


if __name__ == "__main__":
    # 빠른 자기점검: mock 백엔드가 결정적인지, 같은 표면형이 cos=1 인지 확인한다.
    names = ["LightRAG", "LightRAG", "Self-RAG", "RAG"]
    vecs = get_embeddings(names, backend="mock")
    print(f"mock 임베딩 {len(vecs)}건, 차원={len(vecs[0])}")
    print(f"cos(LightRAG, LightRAG) = {cosine(vecs[0], vecs[1]):.4f}  (결정적이면 1.0000)")
    print(f"cos(Self-RAG, RAG)      = {cosine(vecs[2], vecs[3]):.4f}  (mock 은 의미 모름)")
