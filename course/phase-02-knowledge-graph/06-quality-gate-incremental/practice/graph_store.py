"""graph_store.py — 경량 그래프 스토어. MERGE·version·delete 의미론을 결정적으로 시뮬레이션.

이 토픽은 Neo4j 를 직접 쓰지 않는다(실적재는 Phase 3). 대신 표준 라이브러리만으로
JSONL 스냅샷 스토어를 만들어 적재 의미론을 먼저 손에 익힌다. 여기서 정한 의미론
(MERGE = 같은 키면 새로 만들지 않고 provenance 누적, version 스탬프, delete = provenance
제거 후 0 이면 tombstone)이 Phase 3 에서 그대로 Neo4j 의 MERGE + Constraint 로 옮겨진다.

핵심 3종:
  MERGE  : 키 (head,type,tail) 가 같으면 새 노드/엣지를 만들지 않고 provenance 를 누적한다.
           같은 입력을 두 번 적재해도 결과가 동일하다(idempotent).
  version: 각 적재(batch)에 version 라벨을 붙이고, 엣지에 first_seen_batch / last_seen_batch 와
           ingested_in(이 엣지를 건드린 batch 목록)을 스탬프한다.
  delete : 특정 source_id 의 provenance 만 제거하고, provenance 가 0 이 된 엣지는 tombstone 한다.
           tombstone 은 soft-delete — 흔적(언제·왜 죽었는지)을 남긴 채 비활성으로 표시한다.

백엔드: JSONL 스냅샷(노드 1줄·엣지 1줄). 외부 의존 0, 결정적. 정렬해 저장해 diff 가 안정적이다.

전제: 표준 라이브러리만. 네트워크·API 키 불필요.
"""

from __future__ import annotations

import json
from pathlib import Path


def edge_key(head: str, type_: str, tail: str) -> str:
    """엣지의 결정적 키. Phase 3 의 MERGE (h)-[:TYPE]->(t) 와 같은 식별 단위."""
    return f"{head}|{type_}|{tail}"


class GraphStore:
    """노드·엣지를 dict 로 들고, JSONL 스냅샷으로 저장/복원한다."""

    def __init__(self) -> None:
        # name -> {name, labels:set, first_seen_batch, last_seen_batch}
        self.nodes: dict[str, dict] = {}
        # edge_key -> {head,type,tail,direction,provenances:[...],
        #              first_seen_batch,last_seen_batch,ingested_in:[...],
        #              tombstone:bool, tombstone_reason, tombstone_batch}
        self.edges: dict[str, dict] = {}

    # ────────────────────────── MERGE (idempotent upsert) ──────────────────────────
    def merge_node(self, name: str, label: str, batch: str) -> None:
        node = self.nodes.get(name)
        if node is None:
            self.nodes[name] = {
                "name": name,
                "labels": [label],
                "first_seen_batch": batch,
                "last_seen_batch": batch,
            }
        else:
            if label not in node["labels"]:
                node["labels"].append(label)
            node["last_seen_batch"] = batch

    def merge_edge(self, rel: dict, batch: str) -> str:
        """엣지를 MERGE 한다. 같은 키면 provenance 를 누적, 없으면 새로 만든다.

        반환: "created" | "accumulated" | "revived"(tombstone 이었다가 되살아남).
        provenance 는 (source_id, start, end) 로 중복 제거해 같은 근거를 두 번 안 쌓는다.
        """
        key = edge_key(rel["head"], rel["type"], rel["tail"])
        existing = self.edges.get(key)

        if existing is None:
            self.edges[key] = {
                "head": rel["head"],
                "type": rel["type"],
                "tail": rel["tail"],
                "direction": rel.get("direction", "asymmetric"),
                "provenances": list(rel.get("provenances", [])),
                "first_seen_batch": batch,
                "last_seen_batch": batch,
                "ingested_in": [batch],
                "tombstone": False,
            }
            return "created"

        # 이미 있는 엣지 → provenance 누적(중복 제거).
        status = "accumulated"
        if existing.get("tombstone"):
            existing["tombstone"] = False
            existing.pop("tombstone_reason", None)
            existing.pop("tombstone_batch", None)
            status = "revived"

        seen = {_prov_id(p) for p in existing["provenances"]}
        for p in rel.get("provenances", []):
            if _prov_id(p) not in seen:
                existing["provenances"].append(p)
                seen.add(_prov_id(p))

        existing["last_seen_batch"] = batch
        if batch not in existing["ingested_in"]:
            existing["ingested_in"].append(batch)
        return status

    def ingest_batch(
        self,
        relations: list[dict],
        node_labels: dict[str, str],
        batch: str,
    ) -> dict[str, int]:
        """한 배치를 MERGE 적재한다. 엣지가 가리키는 노드도 함께 MERGE 한다.

        node_labels: name -> label(Model/Tool/...) 매핑(canonical_entities 에서).
        반환: {"created":n, "accumulated":n, "revived":n} 카운트.
        """
        counts = {"created": 0, "accumulated": 0, "revived": 0}
        for rel in relations:
            for end in (rel["head"], rel["tail"]):
                self.merge_node(end, node_labels.get(end, "Unknown"), batch)
            status = self.merge_edge(rel, batch)
            counts[status] += 1
        return counts

    # ────────────────────────────── delete ──────────────────────────────
    def delete_source(self, source_id: str, batch: str) -> dict[str, int]:
        """소스 문서 철회. 해당 source_id 의 provenance 만 모든 엣지에서 제거하고,
        provenance 가 0 이 된 엣지는 tombstone(soft-delete) 한다.

        반환: {"provenances_removed":n, "tombstoned":n}.
        hard-delete(딕셔너리에서 제거) 대신 tombstone 으로 두는 이유는 본문 참조 —
        고아 노드·끊긴 멀티홉 경로를 만들지 않고 "언제 왜 죽었는지"를 남기기 위해서다.
        """
        removed = 0
        tombstoned = 0
        for edge in self.edges.values():
            if edge.get("tombstone"):
                continue
            before = len(edge["provenances"])
            edge["provenances"] = [
                p for p in edge["provenances"] if p.get("source_id") != source_id
            ]
            removed += before - len(edge["provenances"])
            if before > 0 and len(edge["provenances"]) == 0:
                edge["tombstone"] = True
                edge["tombstone_reason"] = f"source {source_id} withdrawn"
                edge["tombstone_batch"] = batch
                tombstoned += 1
        return {"provenances_removed": removed, "tombstoned": tombstoned}

    # ────────────────────────────── 통계 ──────────────────────────────
    def stats(self) -> dict[str, int]:
        """적재 전후를 숫자로 비교하기 위한 그래프 통계."""
        live_edges = [e for e in self.edges.values() if not e.get("tombstone")]
        tombstoned = [e for e in self.edges.values() if e.get("tombstone")]
        # 살아 있는 엣지가 한 번도 가리키지 않는 노드 = 고아.
        referenced: set[str] = set()
        for e in live_edges:
            referenced.add(e["head"])
            referenced.add(e["tail"])
        orphan = [n for n in self.nodes if n not in referenced]
        total_support = sum(len(e["provenances"]) for e in live_edges)
        return {
            "nodes": len(self.nodes),
            "live_edges": len(live_edges),
            "tombstoned_edges": len(tombstoned),
            "orphan_nodes": len(orphan),
            "total_support": total_support,
        }

    def live_edges(self) -> list[dict]:
        edges = [e for e in self.edges.values() if not e.get("tombstone")]
        return sorted(edges, key=lambda e: (e["head"], e["type"], e["tail"]))

    # ────────────────────────────── 스냅샷 I/O ──────────────────────────────
    def save(self, path: Path) -> None:
        """노드·엣지를 정렬해 JSONL 스냅샷으로 저장한다. 이 스냅샷이 Phase 3 의 입력."""
        lines: list[str] = []
        for name in sorted(self.nodes):
            lines.append(json.dumps({"kind": "node", **self.nodes[name]}, ensure_ascii=False))
        for key in sorted(self.edges):
            lines.append(json.dumps({"kind": "edge", **self.edges[key]}, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "GraphStore":
        store = cls()
        if not path.exists():
            return store
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.pop("kind")
            if kind == "node":
                store.nodes[row["name"]] = row
            else:
                store.edges[edge_key(row["head"], row["type"], row["tail"])] = row
        return store


def _prov_id(p: dict) -> tuple:
    """provenance 의 결정적 식별자. 같은 근거를 두 번 누적하지 않기 위한 키."""
    return (p.get("source_id"), p.get("start"), p.get("end"))
