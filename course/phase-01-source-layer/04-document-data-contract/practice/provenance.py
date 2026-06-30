"""provenance.py — content_hash 계산 · version 포맷 · provenance 체인 빌더.

이 모듈은 모델에 의존하지 않는 순수 함수만 둔다(Pydantic import 없음).
data_contract.py 가 이 함수들을 import 해서 쓴다. 순환 import 를 막으려고
"계산 로직(여기)"과 "스키마(data_contract.py)"를 갈라 놓았다.

핵심 두 가지:
  1) content_hash — 본문을 '정규화한 뒤' sha256 으로 해시한 짧은 값.
     정규화 없이 해시하면 무의미한 개행·트레일링 공백 차이로 해시가 흔들린다.
  2) version 문자열 — revision(정수)과 content_hash 를 합쳐 'v{n}@{hash}' 형태로.
     정수 revision 은 순서를, content_hash 는 내용 동일성을 책임진다. 둘을 함께 쓴다.

전제: 표준 라이브러리(hashlib)만 쓴다. 네트워크·API 키·외부 의존 없음.
"""

from __future__ import annotations

import hashlib

# content_hash 의 짧은 길이(앞 8글자). 충돌 가능성은 강의 코퍼스 규모에서 무시 가능.
SHORT_HASH_LEN = 8


def normalize_text(text: str) -> str:
    """해시 계산 전에 본문을 정규화한다.

    하는 일:
      - 개행을 LF(\\n) 로 통일(CRLF·CR 흡수). 윈도/맥 차이로 해시가 갈리지 않게.
      - 각 줄 끝 공백 제거. 에디터가 슬쩍 붙이는 트레일링 공백이 해시를 흔들지 못하게.
      - 문서 끝의 빈 줄 정리(맨 끝 개행 1개로 수렴).

    의도적으로 '본문 글자'는 건드리지 않는다. 띄어쓰기·문장은 그대로 둔다.
    여기서 너무 공격적으로 정규화하면(예: 모든 공백 1칸으로) 원문 offset 이 어긋나
    source span 검증이 깨진다. 그래서 '줄 끝·개행'만 손댄다.
    """
    # 1) 개행 통일
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    # 2) 각 줄 트레일링 공백 제거
    lines = [line.rstrip() for line in unified.split("\n")]
    # 3) 끝쪽 빈 줄 제거 후 개행 1개로 마무리
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def content_hash(text: str, *, short: bool = True) -> str:
    """정규화한 본문의 sha256 해시. short=True 면 앞 8글자만.

    반환 형태: 'sha256:ab12cd34' (short) 또는 'sha256:<64자 전체>'.
    'sha256:' 접두를 붙여 어떤 알고리즘인지 자기설명적으로 남긴다.
    """
    normalized = normalize_text(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if short:
        digest = digest[:SHORT_HASH_LEN]
    return f"sha256:{digest}"


def make_version(revision: int, hash_value: str) -> str:
    """revision(정수) + content_hash 를 합친 version 문자열.

    예: revision=1, hash_value='sha256:ab12cd34' -> 'v1@ab12cd34'.
    'sha256:' 접두는 version 표기에서는 떼서 짧게 보여 준다(계약 필드에는 풀로 보관).
    """
    short = hash_value.split(":", 1)[-1]
    return f"v{revision}@{short}"


def make_source_id_from_stem(stem: str) -> str:
    """파일 stem 에서 01/02 규약의 stable ID 를 만든다. '01-rag' -> 'src-01-rag'.

    02 to_wiki.make_source_id 와 같은 결과를 낸다(거기선 경로 기반, 여기선 stem 기반).
    이미 src- 로 시작하면 그대로 둔다(중복 접두 방지).
    """
    if stem.startswith("src-"):
        return stem
    return f"src-{stem}"


def make_step(stage: str, tool: str | None = None, note: str | None = None) -> dict:
    """provenance 체인의 한 단계를 dict 로 만든다(모델 비의존).

    data_contract.Provenance 가 이 dict 리스트를 받아 ProvenanceStep 으로 검증한다.
    여기서 모델을 import 하지 않는 이유: 순환 import 방지.
    """
    return {"stage": stage, "tool": tool, "note": note}


def default_chain(parser: str = "none") -> list[dict]:
    """이 강의 코퍼스의 표준 가공 이력 체인.

    원문 → 파싱 → 정규화 → wiki 4단계. parser 는 03 에서 고른 파서명을 받는다
    (예: 'docling' / 'mineru' / 'none'). 'none' 은 PDF 가 아니라 이미 Markdown 인 경우.
    """
    return [
        make_step("source", note="원문 확보(arXiv/문서 URL 또는 로컬 파일)"),
        make_step("parse", tool=parser, note="PDF→Markdown 변환(03 토픽). Markdown 원본이면 none"),
        make_step("normalize", note="개행 통일·트레일링 공백 제거(content_hash 계산 기준)"),
        make_step("wiki", note="YAML 프런트매터·WikiLink 부착(02 토픽)"),
    ]
