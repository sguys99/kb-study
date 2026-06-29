"""임베딩 헬퍼 — VoyageAI(기본) / 로컬 bge-m3(비용 대안) 분기.

전제:
  - 기본: VOYAGE_API_KEY 환경변수 필요.
  - 대안: USE_LOCAL_EMBEDDING=1 이면 sentence-transformers 로 bge-m3 사용
          (pip install sentence-transformers 필요, API 키 불필요).

failure_demo.py 와 healthcheck.py 가 공통으로 가져다 쓴다.
"""

from __future__ import annotations

import os

import numpy as np


def _use_local() -> bool:
    return os.environ.get("USE_LOCAL_EMBEDDING", "0") == "1"


def embed_documents(texts: list[str]) -> np.ndarray:
    """문서 리스트를 임베딩해 (n, dim) ndarray 로 반환한다."""
    return _embed(texts, input_type="document")


def embed_query(text: str) -> np.ndarray:
    """단일 질의를 임베딩해 (dim,) ndarray 로 반환한다."""
    return _embed([text], input_type="query")[0]


def _embed(texts: list[str], input_type: str) -> np.ndarray:
    if _use_local():
        return _embed_local(texts)
    return _embed_voyage(texts, input_type)


def _embed_voyage(texts: list[str], input_type: str) -> np.ndarray:
    # VoyageAI: voyage-3.5, 기본 차원 1024. 키는 VOYAGE_API_KEY 환경변수에서 읽는다.
    import voyageai

    client = voyageai.Client()  # VOYAGE_API_KEY 자동 사용
    result = client.embed(texts, model="voyage-3.5", input_type=input_type)
    return np.array(result.embeddings, dtype=np.float32)


def _embed_local(texts: list[str]) -> np.ndarray:
    # 비용 대안: 로컬 bge-m3. 결과 품질은 떨어질 수 있으나 파이프라인은 동일하게 동작한다.
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-m3")
    vecs = model.encode(texts, normalize_embeddings=True)
    return np.array(vecs, dtype=np.float32)


def cosine_topk(query_vec: np.ndarray, doc_matrix: np.ndarray, k: int) -> list[int]:
    """코사인 유사도 상위 k개 문서 인덱스를 반환한다."""
    q = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    d = doc_matrix / (np.linalg.norm(doc_matrix, axis=1, keepdims=True) + 1e-8)
    scores = d @ q
    return list(np.argsort(-scores)[:k])
