"""vector_index.py — Vector(Dense) 색인·검색. 의미 유사도로 검색한다.

기본: VoyageAI voyage-3.5 임베딩 + 코사인 유사도.
폴백(비용 0): VOYAGE_API_KEY 가 없으면 결정론적 해시 임베딩으로 자동 전환한다.
  - 순수 표준 라이브러리(hashlib)만 쓴다. 네트워크 0. 키 0.
  - 토큰 해시를 차원 bucket 에 누적해 만든 '가짜 임베딩'이다. 의미를 거의 못 잡는다.
  - 목적은 labs 전체가 키 없이 끝까지 돌게 하는 것뿐. 실측 품질로 착각하면 안 된다
    (eval 결과 meta.embed_backend 가 'hash-fallback' 이면 점수는 데모용이다).
  - 진짜 로컬 품질이 필요하면 bge-m3(예: sentence-transformers 또는 Ollama embeddings)로
    이 클래스의 embed_documents/embed_query 만 갈아끼우면 된다(1~2줄).

input_type 주의: VoyageAI 는 document/query 를 구분한다. 문서 색인엔 "document",
질의엔 "query" 를 줘야 검색 품질이 산다. 둘을 섞으면 점수가 흐트러진다.

임베딩 캐시: out/emb_<backend>.npy + out/emb_ids.json 으로 문서 임베딩을 저장한다.
  같은 청크 집합이면 재실행 시 API 를 다시 부르지 않는다(비용·시간 절약).

전제: 기본 경로는 VOYAGE_API_KEY + voyageai. 폴백 경로는 표준 라이브러리 + numpy.
의존: numpy. (voyageai 는 키 있을 때만 import.)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from load_chunks import OUT_DIR, Chunk

EMBED_MODEL = "voyage-3.5"  # SSOT 기본값. voyage-4 계열이 나왔어도 roadmap 기본은 유지한다.
HASH_DIM = 256  # 폴백 해시 임베딩 차원. 작게 잡아 빠르게.


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    """행 단위 L2 정규화. 정규화하면 코사인 유사도가 내적 한 번으로 끝난다."""
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # 0 벡터 나눗셈 방지.
    return mat / norms


def _hash_embed(texts: list[str]) -> np.ndarray:
    """결정론적 해시 임베딩(폴백). 표준 라이브러리만. 네트워크 0.

    각 토큰을 sha1 해시로 차원 bucket 에 매핑해 +1/-1 부호로 누적한다.
    같은 입력은 늘 같은 벡터를 준다(결정론적). 의미는 거의 못 잡는다 — 데모용.
    """
    import re

    tok_re = re.compile(r"[A-Za-z0-9]+|[가-힣]")
    vecs = np.zeros((len(texts), HASH_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for tok in tok_re.findall(t.lower()):
            h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
            dim = h % HASH_DIM
            sign = 1.0 if (h // HASH_DIM) % 2 == 0 else -1.0
            vecs[i, dim] += sign
    return _l2_normalize(vecs)


class VectorIndex:
    """Dense 색인. 백엔드(voyage/hash)는 키 유무로 자동 결정된다."""

    def __init__(self, chunks: list[Chunk], use_cache: bool = True) -> None:
        self.chunk_ids: list[str] = [c.chunk_id for c in chunks]
        self.backend = "voyage" if os.environ.get("VOYAGE_API_KEY") else "hash-fallback"
        self._client = None  # voyage 일 때만 채운다.
        texts = [c.text for c in chunks]
        self.doc_emb = self._load_or_embed_documents(texts, use_cache)

    # --- 임베딩 백엔드 -------------------------------------------------
    def _voyage_client(self):
        if self._client is None:
            import voyageai  # 키 있을 때만 import(없는 환경에서 import 에러 방지).

            self._client = voyageai.Client()  # VOYAGE_API_KEY 를 자동으로 읽는다.
        return self._client

    def _embed(self, texts: list[str], input_type: str) -> np.ndarray:
        """input_type='document'|'query'. 백엔드에 맞게 임베딩하고 L2 정규화해 돌려준다."""
        if self.backend == "voyage":
            client = self._voyage_client()
            res = client.embed(texts, model=EMBED_MODEL, input_type=input_type)
            mat = np.asarray(res.embeddings, dtype=np.float32)
            return _l2_normalize(mat)
        # 폴백: input_type 은 무시(해시 임베딩엔 구분이 없다).
        return _hash_embed(texts)

    def embed_query(self, query: str) -> np.ndarray:
        return self._embed([query], input_type="query")[0]

    # --- 캐시 ----------------------------------------------------------
    def _cache_paths(self) -> tuple[Path, Path]:
        return OUT_DIR / f"emb_{self.backend}.npy", OUT_DIR / f"emb_ids_{self.backend}.json"

    def _load_or_embed_documents(self, texts: list[str], use_cache: bool) -> np.ndarray:
        emb_path, ids_path = self._cache_paths()
        if use_cache and emb_path.is_file() and ids_path.is_file():
            cached_ids = json.loads(ids_path.read_text(encoding="utf-8"))
            if cached_ids == self.chunk_ids:  # 같은 청크 집합이면 캐시 재사용.
                return np.load(emb_path)
        emb = self._embed(texts, input_type="document")
        if use_cache:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            np.save(emb_path, emb)
            ids_path.write_text(json.dumps(self.chunk_ids, ensure_ascii=False), encoding="utf-8")
        return emb

    # --- 검색 ----------------------------------------------------------
    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """질의 임베딩과 문서 임베딩의 코사인 유사도 상위 k개 (chunk_id, score)."""
        q = self.embed_query(query)  # 이미 L2 정규화됨.
        sims = self.doc_emb @ q  # 정규화돼 있으니 내적 = 코사인.
        order = np.argsort(-sims)[:k]
        return [(self.chunk_ids[i], float(sims[i])) for i in order]


if __name__ == "__main__":
    # 빠른 자기점검: 백엔드를 출력하고 의미 질의를 한 번 던진다.
    from load_chunks import load_chunks

    chunks = load_chunks()
    vidx = VectorIndex(chunks)
    cmap = {c.chunk_id: c for c in chunks}
    print(f"[vector] backend={vidx.backend}  dim={vidx.doc_emb.shape[1]}")
    q = "임베딩 기반 의미 검색"
    for cid, score in vidx.search(q, k=5):
        print(f"  {score:6.3f}  {cid:22s}  {cmap[cid].quote[:40]!r}")
