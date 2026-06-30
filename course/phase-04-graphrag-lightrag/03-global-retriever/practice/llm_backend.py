"""4.3 llm_backend.py — LLM 호출 한 군데로 모으기. Claude 기본, Ollama 로컬 대안.

community_summarize.py 와 global_retriever.py 가 같은 규약으로 LLM 을 부르도록
호출부를 이 한 파일로 모은다. 백엔드 선택 규칙은 단순하다.

    ANTHROPIC_API_KEY 가 있고 anthropic 패키지가 깔려 있으면 → Claude
    그 외에는 → Ollama 로컬(http://localhost:11434, 키 불필요·과금 0)

이렇게 두면 키가 있는 학습자는 Claude 로, 비용을 0 으로 가려는 학습자는 Ollama 로
'코드 수정 없이' 같은 파이프라인을 돈다. 결과 품질만 다르고 흐름은 같다.

비용 0 대안(Ollama) 준비:
    1) https://ollama.com 에서 설치 후 `ollama serve`
    2) `ollama pull qwen2.5:7b`   (가벼운 한국어 지원 모델 예시. 다른 모델도 가능)
    3) export OLLAMA_MODEL=qwen2.5:7b   (생략하면 기본값 사용)
    키를 안 넣으면 자동으로 이 경로로 떨어진다.

전제:
    - Claude 경로: ANTHROPIC_API_KEY 환경변수 + `pip install anthropic`.
      키는 os.environ 에서만 읽는다. 하드코딩 금지.
    - Ollama 경로: 추가 패키지 불필요(표준 라이브러리 urllib 사용). ollama 가 떠 있어야 함.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# 현행 Claude 모델 id — 빠르게 바뀌므로 작성 시점 기준값. 환경변수로 덮어쓸 수 있다.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Ollama 로컬 모델. 받아 둔 모델 이름으로 바꾼다.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def active_backend() -> str:
    """어떤 백엔드로 돌지 결정한다. 'anthropic' 또는 'ollama'.

    키가 있고 패키지가 import 되면 Claude, 아니면 Ollama. 호출 전에 한 번 찍어 두면
    학습자가 '지금 무엇으로 도는지' 헷갈리지 않는다.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401  (설치 여부만 확인)
            return "anthropic"
        except ImportError:
            pass
    return "ollama"


def _complete_anthropic(prompt: str, max_tokens: int) -> str:
    """Claude messages.create 한 번 호출. 텍스트 한 덩어리를 돌려준다."""
    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 를 환경변수에서 자동으로 읽는다.
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    # content 는 블록 리스트다. text 블록만 모아 잇는다.
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


def _complete_ollama(prompt: str, max_tokens: int) -> str:
    """Ollama /api/generate 한 번 호출(표준 라이브러리만). 스트리밍 끄고 한 번에 받는다."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data.get("response") or "").strip()
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Ollama 호출 실패({OLLAMA_URL}). `ollama serve` 가 떠 있고 "
            f"`ollama pull {OLLAMA_MODEL}` 로 모델을 받았는지 확인하라."
        ) from exc


def complete(prompt: str, max_tokens: int = 512) -> str:
    """프롬프트 하나를 활성 백엔드로 보내 텍스트 답을 받는다.

    summarize·global 둘 다 이 함수만 부른다. 백엔드 분기는 여기서 끝난다.
    """
    backend = active_backend()
    if backend == "anthropic":
        return _complete_anthropic(prompt, max_tokens)
    return _complete_ollama(prompt, max_tokens)
