"""resolve_entities.py — 4단계 엔티티 해소(Entity Resolution) + 클러스터링 + 재배선.

2/02·2/03 은 표면형(surface form)을 그대로 점으로 찍었다. 그래서 같은 개체가
여러 표기·여러 문서에서 중복으로 들어온다. entities.jsonl 에는 LightRAG 가 4번,
RAG 가 3번, GraphRAG 가 3번 들어 있다(서로 다른 문서·offset). 이걸 합치지 않으면
그래프에 같은 점이 여러 개가 되고, 멀티홉 경로가 끊기고, 카운트가 부풀려진다.

병합은 한 방에 하지 않는다. 싼 것부터 비싼 것 순으로 4단계를 쌓는다:

  1) alias 사전 병합 — exact / normalized 매칭 + aliases 필드. 가장 싸고 확실.
  2) coreference 해소 — 같은 문서(source_id) 안에서 같은 표면형은 같은 개체.
  3) fuzzy 매칭     — 문자열 유사도(rapidfuzz). 오타·표기 흔들림. substring 가드 필수.
  4) embedding 병합 — 의미 중복. 코사인 유사도(mock/voyage/local 백엔드).

각 단계는 '병합 후보 쌍'의 집합을 만든다. 단계가 끝나면 모든 쌍을 Union-Find 로
연결요소(클러스터)로 묶는다. 클러스터마다 canonical(대표) 이름을 정하고, 나머지는
alias 로 흡수한다. 마지막에 relations 의 head/tail 을 canonical 로 재배선한다.

⚠️ substring 함정: Self-RAG·CRAG 는 RAG 를 부분문자열로 포함하지만 '다른 모델'이다.
   절대 RAG 로 병합하면 안 된다. fuzzy·embedding 단계가 type 일치·임계값·단어경계로
   이걸 막는다. 이 가드가 깨지면 그래프가 거짓 사실을 만든다.

전제: 기본 경로(mock)는 rapidfuzz + pydantic 만 있으면 키 없이 돈다.
의존: rapidfuzz, pydantic>=2. (embedding voyage/local 백엔드는 선택)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from embedding_provider import cosine, get_embeddings
from schema_adapter import Entity, Relation

# ─────────────────────────────────────────────────────────────────────────────
# 0) 정규화 — 모든 단계가 공유하는 표면형 정규화. "표기 흔들림"을 한 곳에서 흡수한다.
# ─────────────────────────────────────────────────────────────────────────────


def normalize(name: str) -> str:
    """표면형을 비교용 키로 정규화한다. exact 매칭은 이 키 위에서 한다.

    하는 일: 유니코드 NFKC → 소문자 → 하이픈·언더스코어를 공백으로 → 공백 압축.
    예: 'Light RAG' / 'light-rag' / 'LightRAG' → 'light rag' / 'light rag' / 'lightrag'.
    주의: 공백/하이픈은 지우지 않고 '공백 하나'로 통일만 한다. 'Light RAG' 와
          'LightRAG' 는 여전히 다른 키다(전자는 'light rag', 후자는 'lightrag').
          그 둘을 합치는 건 alias 필드나 fuzzy 단계의 몫이다.
    """
    s = unicodedata.normalize("NFKC", name).strip().lower()
    s = re.sub(r"[-_]+", " ", s)        # 하이픈·언더스코어 → 공백
    s = re.sub(r"\s+", " ", s)          # 연속 공백 → 하나
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Union-Find (Disjoint Set) — 병합 후보 쌍들을 연결요소(클러스터)로 묶는다.
# ─────────────────────────────────────────────────────────────────────────────


class UnionFind:
    """경로 압축 + union by size. 인덱스(엔티티 위치) 단위로 동작한다."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # 경로 압축
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]

    def clusters(self) -> dict[int, list[int]]:
        """root → 멤버 인덱스 목록."""
        out: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            out.setdefault(self.find(i), []).append(i)
        return out


# 병합 후보 쌍: 엔티티 리스트 안의 두 인덱스. 단계 이름과 함께 들고 다닌다(추적용).
@dataclass
class MergePair:
    i: int
    j: int
    stage: str  # "alias" | "coref" | "fuzzy" | "embedding"
    detail: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# 1단계: alias 사전 병합 — exact / normalized + aliases 필드.
# ─────────────────────────────────────────────────────────────────────────────


def stage_alias(entities: list[Entity]) -> list[MergePair]:
    """normalize() 키가 같으면 병합 후보. aliases 필드도 키로 친다.

    type 이 다르면 후보에서 제외한다(Model 'RAG' 와 Concept 'rag' 는 다른 개체).
    가장 싸고 확실한 1차 병합이다. 'LightRAG' 4건이 여기서 거의 다 묶인다.
    """
    pairs: list[MergePair] = []
    # (normalized_key, type) → 대표 인덱스. 이름과 aliases 를 모두 키로 등록한다.
    seen: dict[tuple[str, str], int] = {}
    for idx, e in enumerate(entities):
        keys = {normalize(e.name)}
        keys.update(normalize(a) for a in e.aliases)
        # 이 엔티티의 어느 키든 이미 본 적 있으면(같은 type) 그 대표와 병합.
        matched: int | None = None
        for k in keys:
            tk = (k, e.type.value)
            if tk in seen:
                matched = seen[tk]
                break
        if matched is not None:
            pairs.append(MergePair(matched, idx, "alias", detail=f"key={normalize(e.name)!r}"))
        # 이 엔티티의 모든 키를 (없으면) 등록한다.
        for k in keys:
            seen.setdefault((k, e.type.value), idx)
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# 2단계: coreference 해소 — 같은 문서 안의 같은 표면형은 같은 개체(문서 내 일관성).
# ─────────────────────────────────────────────────────────────────────────────


def stage_coref(entities: list[Entity]) -> list[MergePair]:
    """같은 source_id 안에서 normalize() 키가 같으면 동일 개체로 본다.

    한 문서가 'RAG' 를 여러 번 언급하면 그건 같은 RAG 다(문서 내 일관성 가정).
    1단계가 type+key 로 이미 잡는 경우가 많지만, coref 는 '문서 경계'를 근거로
    명시적으로 한 번 더 묶는다. 룰 기반이 기본이다. 같은 표면형이라도 문서가
    다르면 여기선 안 묶는다 — 그건 alias/fuzzy/embedding 단계가 판단한다.
    LLM 보조 coref(대명사·약어 해소)는 선택이며 키가 필요하므로 여기선 다루지 않는다.
    """
    pairs: list[MergePair] = []
    # (source_id, normalized_key, type) → 첫 인덱스.
    seen: dict[tuple[str, str, str], int] = {}
    for idx, e in enumerate(entities):
        tk = (e.provenance.source_id, normalize(e.name), e.type.value)
        if tk in seen:
            pairs.append(
                MergePair(seen[tk], idx, "coref", detail=f"doc={e.provenance.source_id}")
            )
        else:
            seen[tk] = idx
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# 3단계: fuzzy 매칭 — 문자열 유사도. 오타·표기 흔들림. substring 함정 가드 포함.
# ─────────────────────────────────────────────────────────────────────────────


def _is_substring_trap(a: str, b: str) -> bool:
    """짧은 이름이 긴 이름 '안에' 들어 있지만 둘은 다른 개체일 위험 — 병합을 막는다.

    이 토픽에서 가장 위험한 케이스다. 'RAG' 는 'Self-RAG'·'CRAG'·'Adaptive RAG' 의
    부분문자열이지만 전부 다른 모델이다. 순진하게 fuzzy 점수만 보면 임계값을 조금만
    낮춰도 이들이 'RAG' 로 빨려 들어간다. 그래서 '함정'을 명시적으로 잡아 후보에서 뺀다.

    두 가지 함정 모양을 본다(둘 중 하나라도 해당하면 함정):
      1) 짧은 쪽이 긴 쪽의 '독립 토큰'으로 등장하고, 긴 쪽이 토큰을 더 가진다.
         'rag' ⊂ 토큰{'self','rag'}, 'rag' ⊂ 토큰{'adaptive','rag'} → 함정.
         (긴 쪽이 RAG 에 무언가를 '덧붙여' 다른 모델을 만든 형태.)
      2) 짧은 쪽이 긴 쪽에 '붙어서'(독립 토큰이 아니게) 들어 있다.
         'rag' ⊂ 'crag', 'rag' ⊂ 'selfrag' → 함정.

    반대로 함정이 아닌 것(정상 병합 대상)은 fuzzy/embedding 단계로 흘려 보낸다:
      'light rag' ~ 'lightrag' — 'rag' 가 'lightrag' 안의 독립 토큰이 아니고,
      'light rag' 도 'lightrag' 의 부분문자열이 아니다 → 함정 아님 → fuzzy 가 병합.
      'neo4j' ~ 'neo4j' — 정규화하면 같은 키라 애초에 fuzzy 까지 오지 않는다.
    """
    sa, sb = sorted([a, b], key=len)  # sa = 짧은 쪽, sb = 긴 쪽
    if sa == sb:
        return False
    tb = sb.split(" ")
    # 1) 짧은 쪽이 단일 토큰이고, 긴 쪽의 독립 토큰으로 등장하며, 긴 쪽이 토큰을 더 가짐.
    if " " not in sa and sa in tb and len(tb) > 1:
        return True
    # 2) 짧은 쪽이 긴 쪽에 '붙어서'(독립 토큰 아님) 들어 있음.
    if sa in sb and sa not in tb:
        return True
    return False


def stage_fuzzy(
    entities: list[Entity],
    threshold: int = 90,
    substring_guard: bool = True,
) -> list[MergePair]:
    """type 이 같은 쌍만 비교. token_sort_ratio 가 threshold 이상이면 후보.

    substring 함정(Self-RAG/RAG, CRAG/RAG)은 _is_substring_trap 으로 먼저 막는다.
    threshold 는 보수적으로 잡는다(기본 90). 임베딩 없이 저비용으로 오타·표기
    흔들림을 잡는 단계다.

    substring_guard 를 끄면(labs 5단계) 가드 없이 어떤 오병합이 나는지 재현할 수
    있다 — 끈 채로 threshold 를 낮추면 Self-RAG·CRAG 가 RAG 로 새는 게 보인다.
    기본은 켬(True). 실전에서 끄지 마라 — 거짓 사실을 만든다.
    """
    pairs: list[MergePair] = []
    n = len(entities)
    for i in range(n):
        for j in range(i + 1, n):
            ei, ej = entities[i], entities[j]
            if ei.type != ej.type:
                continue  # type 이 다르면 후보 제외(가장 강한 가드)
            ni, nj = normalize(ei.name), normalize(ej.name)
            if ni == nj:
                continue  # 이미 1·2단계가 잡음
            if substring_guard and _is_substring_trap(ni, nj):
                continue  # substring 함정 — 막는다
            score = fuzz.token_sort_ratio(ni, nj)
            if score >= threshold:
                pairs.append(
                    MergePair(i, j, "fuzzy", detail=f"{ni!r}~{nj!r} score={score}")
                )
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# 4단계: embedding 병합 — 의미 중복을 코사인 유사도로. mock/voyage/local 백엔드.
# ─────────────────────────────────────────────────────────────────────────────


def stage_embedding(
    entities: list[Entity],
    backend: str = "mock",
    threshold: float = 0.92,
    substring_guard: bool = True,
) -> list[MergePair]:
    """type 이 같은 쌍만 코사인 유사도로 비교. threshold 이상이면 후보.

    alias·fuzzy 가 못 잡는 의미 중복(예: 'Knowledge Graph' ~ 'KG')을 노린다.
    여기서도 type 일치와 substring 함정 가드를 그대로 적용한다 — 임베딩이라고
    Self-RAG 를 RAG 로 합치게 두면 안 된다.

    ⚠️ backend='mock' 은 의미를 모른다(같은 표면형=같은 벡터, 다르면 거의 직교).
       그래서 mock 에서는 1·2단계가 이미 잡은 것 외에 추가 병합이 거의 안 난다.
       이건 정상이다. 의미 병합의 실제 효과는 voyage/local 백엔드에서 확인한다.
    """
    pairs: list[MergePair] = []
    names = [e.name for e in entities]
    vecs = get_embeddings(names, backend=backend)
    n = len(entities)
    for i in range(n):
        for j in range(i + 1, n):
            ei, ej = entities[i], entities[j]
            if ei.type != ej.type:
                continue
            ni, nj = normalize(ei.name), normalize(ej.name)
            if ni == nj or (substring_guard and _is_substring_trap(ni, nj)):
                continue
            sim = cosine(vecs[i], vecs[j])
            if sim >= threshold:
                pairs.append(
                    MergePair(i, j, "embedding", detail=f"{ni!r}~{nj!r} cos={sim:.3f}")
                )
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# 클러스터링 → canonical 선정 → merge_map → relation 재배선.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Cluster:
    """병합된 한 클러스터. canonical 1건 + 흡수된 멤버들."""

    canonical_id: str
    canonical_name: str
    type: str
    members: list[str] = field(default_factory=list)  # 원본 표면형들(중복 포함 가능)
    aliases: list[str] = field(default_factory=list)   # canonical 외 표면형(고유)


def _slug(name: str) -> str:
    """canonical_id 용 슬러그. 영숫자만 남기고 공백·기호는 하이픈으로."""
    s = normalize(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "x"


def select_canonical(members: list[Entity]) -> Entity:
    """클러스터 대표를 고른다. 규칙: 가장 빈번한 표면형 → 동률이면 가장 긴 → 최초 등장.

    빈도를 1순위로 두는 이유: 코퍼스가 실제로 가장 많이 쓰는 표기가 대표가 돼야
    Neo4j 적재·GraphRAG 인용에서 자연스럽다. 'LightRAG'(4회)가 'Light RAG'(1회)를
    이긴다. 동률이면 더 완전한(긴) 표기를 택한다.
    """
    from collections import Counter

    freq = Counter(m.name for m in members)
    best_name = max(
        freq,
        key=lambda nm: (freq[nm], len(nm)),  # (빈도, 길이) 사전식 최대
    )
    # best_name 을 surface 로 가진 첫 멤버를 대표 엔티티로(provenance 보존).
    for m in members:
        if m.name == best_name:
            return m
    return members[0]


def cluster_entities(entities: list[Entity], pairs: list[MergePair]) -> list[Cluster]:
    """병합 쌍을 Union-Find 로 묶고, 클러스터마다 canonical 을 정한다."""
    uf = UnionFind(len(entities))
    for p in pairs:
        uf.union(p.i, p.j)

    clusters: list[Cluster] = []
    for _, idxs in uf.clusters().items():
        members = [entities[i] for i in idxs]
        canon = select_canonical(members)
        ctype = canon.type.value
        cid = f"ent-{ctype.lower()}-{_slug(canon.name)}"
        # alias = canonical 과 표면형이 다른 멤버들 + 멤버들이 들고 온 기존 aliases.
        alias_set: set[str] = set()
        for m in members:
            if m.name != canon.name:
                alias_set.add(m.name)
            alias_set.update(m.aliases)
        alias_set.discard(canon.name)
        clusters.append(
            Cluster(
                canonical_id=cid,
                canonical_name=canon.name,
                type=ctype,
                members=[m.name for m in members],
                aliases=sorted(alias_set),
            )
        )
    return clusters


def build_merge_map(clusters: list[Cluster]) -> dict[str, str]:
    """원본 표면형 → canonical_name 매핑. relation 재배선과 검증에 쓴다.

    한 표면형(예: 'RAG')이 정확히 하나의 canonical 로만 가야 한다. 같은 표면형이
    여러 클러스터에 흩어지면(예: alias 가 충돌하면) 마지막 클러스터가 이긴다 —
    validate_resolution 이 이 1:1 성질을 회귀 테스트로 잡는다.
    """
    mapping: dict[str, str] = {}
    for c in clusters:
        for surface in set(c.members) | set(c.aliases):
            mapping[surface] = c.canonical_name
        mapping[c.canonical_name] = c.canonical_name
    return mapping


def rewire_relations(
    relations: list[Relation], merge_map: dict[str, str]
) -> list[Relation]:
    """relation 의 head/tail 표면형을 canonical 이름으로 바꾼다.

    merge_map 에 없는 이름(엔티티 추출이 놓친 dangling)은 그대로 둔다 —
    validate_resolution 이 dangling 으로 잡는다. provenance·type 은 보존한다.
    """
    out: list[Relation] = []
    for r in relations:
        new_head = merge_map.get(r.head, r.head)
        new_tail = merge_map.get(r.tail, r.tail)
        out.append(
            Relation(
                head=new_head,
                type=r.type,
                tail=new_tail,
                provenance=r.provenance,
            )
        )
    return out


def resolve(
    entities: list[Entity],
    relations: list[Relation],
    *,
    embedding_backend: str = "mock",
    fuzzy_threshold: int = 90,
    embedding_threshold: float = 0.92,
    substring_guard: bool = True,
) -> tuple[list[Cluster], dict[str, str], list[Relation], list[MergePair]]:
    """4단계 ER 전체를 한 번에 돌린다. 단계별 쌍을 모두 모아 클러스터링한다.

    반환: (clusters, merge_map, rewired_relations, all_pairs).
    all_pairs 는 어느 단계가 무엇을 병합했는지 리포트·디버깅용으로 함께 넘긴다.
    substring_guard=False 는 labs 5단계(오병합 재현)용이다. 실전에서 끄지 마라.
    """
    pairs: list[MergePair] = []
    pairs += stage_alias(entities)
    pairs += stage_coref(entities)
    pairs += stage_fuzzy(
        entities, threshold=fuzzy_threshold, substring_guard=substring_guard
    )
    pairs += stage_embedding(
        entities,
        backend=embedding_backend,
        threshold=embedding_threshold,
        substring_guard=substring_guard,
    )
    clusters = cluster_entities(entities, pairs)
    merge_map = build_merge_map(clusters)
    rewired = rewire_relations(relations, merge_map)
    return clusters, merge_map, rewired, pairs
