# 1.3 PDF·표·수식 파싱 — Docling·MinerU·RAG-Anything 비교

> **Phase 1 · 토픽 03** · 01·02가 전제한 깨끗한 Markdown은 어디서 오는가. 표·수식·2단 레이아웃·한국어가 섞인 PDF를 세 파서(Docling·MinerU·RAG-Anything)로 변환해, 무엇이 얼마나 보존되는지 같은 입력으로 비교한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 같은 PDF 한 건을 Docling·MinerU·RAG-Anything 세 파서로 각각 Markdown으로 변환하고, 산출물을 `out/<parser>/`에 따로 떨군다.
- 표 보존(Markdown table 블록 수)·수식 보존(`$...$`/LaTeX 토큰 수)·한국어 보존(한글 음절 비율)을 한 표로 정량 비교하는 하니스를 직접 돌린다.
- 입력 특성(영어/한국어, 구조화 표/수식, 스캔 여부, 멀티모달 통합 여부)에 따라 when-to-use 매트릭스로 파서를 고른다.

**완료 기준**: `python compare_parsers.py`가 세 파서의 표 블록 수·수식 토큰 수·한국어 보존율을 한 표로 출력하고, 각 파서 산출 Markdown이 `out/docling/`·`out/mineru/`·`out/raganything/`에 저장되면 완료.

---

## 1. 왜 필요한가 — 그 깨끗한 .md는 거짓말이다

02에서 우리는 깨끗한 Markdown 8건을 입력으로 받았다. `practice/sources/01-rag.md`부터 `08-multihop.md`까지, 표도 멀쩡하고 수식도 안 깨지고 한글도 온전한 파일들. 거기에 프런트매터를 얹고 WikiLink를 그어 LLM Wiki를 만들었다.

그 8건은 사람이 손으로 정제한 것이다. 실제 러닝 코퍼스는 그렇지 않다. arXiv의 RAG·GraphRAG 논문은 2단 레이아웃에 표가 박혀 있고, 수식이 본문 곳곳에 흐르고, 한국어 기술 문서라면 OCR을 거쳐야 한다. PDF다. 누군가 이 PDF를 충실한 Markdown으로 바꿔 줘야 02가 가정한 그 깨끗한 입력이 생긴다.

그 변환을 대충 하면 어떻게 되는지는 Phase 0에서 이미 봤다. "RAG가 무너지는 4가지 실패" 중 첫째가 쓰레기 입력이다. 표가 줄글로 뭉개지면 "2021년 매출과 2022년 매출을 비교하라" 같은 멀티홉·수치 질문이 통째로 깨진다. 셀이 어디로 갔는지 검색기가 알 수 없으니까. 수식이 OCR로 깨져 `∑` 가 `5` 가 되면 그 수식은 인용조차 못 한다. 2단 레이아웃의 reading order가 꼬이면 왼쪽 칸 문장과 오른쪽 칸 문장이 뒤섞여, 청킹 단계에서 말이 안 되는 덩어리가 나온다.

그래서 03은 변환 단계를 정면으로 다룬다. 그리고 변환기는 하나가 아니다. 같은 PDF라도 파서마다 표를 살리는 정도, 수식을 LaTeX로 남기는 정도, 한국어를 안 깨뜨리는 정도가 다르다. 어느 파서가 무엇을 얼마나 보존하는가는 04의 source span(원문 위치 추적)과 인용 품질을 그대로 좌우한다. 표가 통째로 뭉개진 Markdown에는 셀 단위 인용을 걸 자리가 없다.

## 2. 세 파서의 포지셔닝 — 직관부터

세 도구는 같은 층에 있지 않다. 먼저 이 지형을 잡아야 비교가 의미 있다.

**Docling**(IBM, docling-project). 레이아웃과 표 구조를 인식하고, 옵션을 켜면 수식을 LaTeX로 뽑아낸다(formula enrichment). 파싱 결과를 `DoclingDocument`라는 단일 표현으로 담아 Markdown이든 JSON이든 내보낸다. 영어 문서, 구조화된 표·수식이 강점이다. gen-AI 생태계 통합도 매끄럽다.

**MinerU**(opendatalab). VLM 기반 고정밀 파서로, 한국어를 포함한 OCR이 강점이다. 스캔 PDF나 한국어 기술 문서를 LLM이 읽기 좋은 Markdown/JSON으로 떨군다. 함정이 하나 있다. 패키지 이름이 예전 `magic-pdf`에서 **`mineru`로 바뀌었다.** 옛 명령을 그대로 쓰면 설치부터 막힌다. 파이썬 API는 버전마다 흔들려서, 여기서는 CLI(`mineru -p ... -o ...`)를 권장 경로로 잡고 코드에서는 subprocess로 감싼다.

**RAG-Anything**(HKUDS). 이건 파서가 아니다. 멀티모달 RAG 올인원 프레임워크다. 내부에서 파서를 *선택*한다 — `parser="mineru"` 또는 `parser="docling"`. 파싱한 결과를 LightRAG로 이어 인덱싱·질의까지 한 파이프라인에 묶는다. 그래서 03에서 RAG-Anything은 "파서 위에 올라가는 통합 계층"으로만 본다. 질의 단계는 Phase 4 LightRAG의 예고편이고, 여기서는 **파싱까지만** 한다.

정리하면 이렇다. Docling과 MinerU는 PDF를 Markdown으로 바꾸는 *파서*다. RAG-Anything은 그 둘 중 하나를 골라 쓰는 *프레임워크*다. 같은 줄에 놓고 "셋 중 뭐가 제일 좋냐"고 물으면 질문이 틀렸다. 앞 둘은 변환 품질로, 뒤 하나는 파이프라인 통합으로 비교한다.

> 세 도구 모두 로컬에서 돈다. 파싱 단계에는 API 키가 필요 없다. 다만 MinerU는 첫 실행 때 VLM 모델을 내려받고 GPU가 있으면 훨씬 빠르다(CPU도 동작은 한다). RAG-Anything의 질의 단계는 LLM·임베딩이 필요하지만 그건 Phase 4 몫이라, 03 범위에서는 키 없이 파싱만 돌린다.

## 3. 실습 — 같은 PDF, 세 파서, 한 표로 비교

### Docling — 기본 변환부터 표·수식까지

기본 변환은 세 줄이다. source는 로컬 경로도 되고 arXiv pdf URL도 받는다.

```python
# practice/parse_docling.py 의 핵심 부분
from docling.document_converter import DocumentConverter

conv = DocumentConverter()
res = conv.convert(source)                 # 로컬 PDF 경로 또는 arXiv pdf URL
md = res.document.export_to_markdown()      # 통짜 Markdown
```

표는 통짜 Markdown만 보면 구조 손실을 못 알아챈다. `DoclingDocument`에서 표를 따로 꺼내 DataFrame으로 확인한다.

```python
for i, table in enumerate(res.document.tables):
    df = table.export_to_dataframe(doc=res.document)   # 행·열이 살아 있는지 직접 본다
    df.to_csv(out_dir / f"table_{i}.csv", index=False)
```

수식은 옵션을 켜야 LaTeX로 남는다. 기본값에서는 수식이 그림처럼 흘러가 버린다.

```python
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import PdfFormatOption

opts = PdfPipelineOptions()
opts.do_formula_enrichment = True          # 수식을 LaTeX 로 추출
conv = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
)
```

### MinerU — CLI 러너

MinerU는 CLI를 subprocess로 감싼다. 설치가 안 돼 있으면 죽지 말고 안내 메시지를 내야 한다.

```python
# practice/parse_mineru.py 의 핵심 부분
import shutil, subprocess

if shutil.which("mineru") is None:
    print("[건너뜀] mineru CLI 가 없다. 설치: uv pip install -U \"mineru[all]\"")
    raise SystemExit(0)

subprocess.run(["mineru", "-p", str(pdf_path), "-o", str(out_dir)], check=True)
# 옛 magic-pdf 명령을 쓰지 말 것. 패키지명이 mineru 로 바뀌었다.
```

### RAG-Anything — 파서를 고르는 계층

RAG-Anything은 설정에서 파서를 고른다. 03에서는 파싱만 호출하고 질의는 안 한다.

```python
# practice/parse_raganything.py 의 핵심 부분
from raganything import RAGAnything, RAGAnythingConfig

config = RAGAnythingConfig(
    working_dir="./rag_storage",
    parser="mineru",          # "docling" 으로 바꿔 파서를 교체할 수 있다
    parse_method="auto",
    enable_image_processing=True,
)
rag = RAGAnything(config=config)
# 질의(rag.aquery)는 LLM·임베딩이 필요하므로 Phase 4 에서 다룬다. 여기서는 파싱 산출물만 본다.
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 파싱에는 API 키가 필요 없다. MinerU 모델 다운로드·GPU 권장만 전제다. RAG-Anything 질의 단계의 LLM·임베딩은 Phase 4에서 붙이며, 비용이 부담되면 그때 임베딩을 `bge-m3`(로컬), LLM을 Ollama로 바꿔도 파이프라인은 동일하다.

### 비교 하니스

세 파서가 떨군 Markdown을 읽어 세 지표를 뽑는다. 표준 라이브러리와 pandas면 된다.

```python
# practice/compare_parsers.py 의 핵심 부분
import re

TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)     # Markdown table 행
FORMULA = re.compile(r"\$[^$\n]+\$|\\\[[^\]]+\\\]")  # $...$ 또는 \[...\] 수식
HANGUL = re.compile(r"[가-힣]")

def metrics(md: str) -> dict:
    table_blocks = count_table_blocks(md)           # 연속된 | 행을 한 블록으로 묶어 센다
    formulas = len(FORMULA.findall(md))
    hangul = len(HANGUL.findall(md))
    return {"table_blocks": table_blocks, "formula_tokens": formulas, "hangul_chars": hangul}
```

한국어 보존율은 입력 PDF의 한글 음절 수를 근사 기준으로 잡고, 산출 Markdown의 한글 수가 그에 얼마나 가까운지로 본다. 정확한 절대값을 재려는 게 아니다. 세 파서를 같은 자로 재어 *상대* 차이를 보려는 것이다.

## 4. 결과 해석 — 무엇을 보고 파서를 고르나

비교 표를 이렇게 읽는다.

```
parser        table_blocks   formula_tokens   hangul_chars   hangul_ratio
docling                 4               12           0           0.00
mineru                  3                2         812           0.97
raganything(mineru)     3                2         805           0.96
```

`table_blocks`가 0이면 표가 줄글로 뭉개졌다는 신호다. 산출 Markdown을 열어 실제로 `| --- |` 구분선이 있는 table로 살았는지 눈으로 확인한다. 통짜 export만 보고 넘어가면 표가 죽은 걸 놓친다. `formula_tokens`는 수식이 `$...$`/LaTeX로 남았는지를 본다. Docling은 formula enrichment를 켜야 이 숫자가 올라간다 — 안 켜면 영어 논문이라도 0에 가깝다. `hangul_chars`/`hangul_ratio`는 한국어 PDF를 넣었을 때 의미가 있다. OCR이 약한 파서는 여기서 비율이 뚝 떨어진다.

위 예시처럼 영어 수식 논문은 Docling이 표·수식을 더 살리고, 한국어 문서는 MinerU(그리고 MinerU를 파서로 쓴 RAG-Anything)가 한글을 더 보존하는 패턴이 자주 나온다. 숫자만 믿지 말고 산출물도 함께 열어 본다.

**when-to-use 매트릭스.**

| 입력 특성 | 권장 파서 | 이유 |
|-----------|-----------|------|
| 영어, 구조화된 표·수식(arXiv 논문 등) | **Docling** | 레이아웃·표 인식 + formula enrichment로 LaTeX 보존 |
| 한국어, 스캔 PDF, OCR 필요 | **MinerU** | VLM 기반 한국어 OCR 강점 |
| 멀티모달 통합 파이프라인(파싱→인덱싱→질의) | **RAG-Anything** | 파서를 골라 LightRAG로 잇는 올인원 (Phase 4로 연결) |

이 결정은 04로 그대로 넘어간다. 표가 table로 살아남은 파서라야 셀 단위 source span을 걸 수 있고, 한글이 안 깨진 파서라야 한국어 인용이 정확하다. 파서 선택이 곧 인용 품질의 상한선이다.

---

## 🚨 자주 하는 실수

1. **옛 `magic-pdf` 명령으로 MinerU를 설치·호출함** — 패키지명이 `mineru`로 바뀌었다. 설치는 `uv pip install -U "mineru[all]"`(또는 `pip install -U "mineru[all]"`), 실행은 `mineru -p <pdf> -o <out>`이다. `pip install magic-pdf`나 `magic-pdf` 명령은 더 이상 권장 경로가 아니다. 검색으로 나온 옛 튜토리얼을 그대로 따라가면 여기서 막힌다.
2. **통짜 `export_to_markdown`만 보고 표가 살았다고 믿음** — 통짜 Markdown에서는 표가 줄글로 뭉개져도 글자는 다 들어 있어 멀쩡해 보인다. Docling이라면 `res.document.tables`를 꺼내 DataFrame으로, 어느 파서든 산출 Markdown에 `| --- |` 구분선이 실제로 있는지 눈으로 확인한다. `compare_parsers.py`의 `table_blocks`가 0이면 표 구조가 죽은 것이다.
3. **OCR이 필요한 스캔 PDF를 그냥 넣고 빈 결과를 받음** — 텍스트 레이어가 없는 스캔 PDF는 OCR을 거쳐야 글자가 나온다. 텍스트 추출만 하는 경로로 돌리면 산출 Markdown이 거의 비어 나온다. 한국어·스캔 문서는 OCR이 강한 MinerU로 보내고, 결과가 비면 입력이 스캔본인지부터 의심한다.
4. **RAG-Anything을 단순 파서로 오해함** — RAG-Anything은 파서가 아니라 LightRAG 기반 멀티모달 RAG 프레임워크다. 내부에서 `parser="mineru"|"docling"`로 실제 파서를 고른다. "RAG-Anything이 Docling보다 표를 잘 뽑나?"는 틀린 질문이다 — RAG-Anything이 Docling을 *부르는* 것이다. 03에서는 파싱 계층으로만 쓰고, 질의는 Phase 4에서 붙인다.

## 출처

- Docling (IBM, docling-project): https://github.com/docling-project/docling
- MinerU (opendatalab): https://github.com/opendatalab/MinerU
- RAG-Anything (HKUDS), arXiv [2510.12323](https://arxiv.org/abs/2510.12323): https://github.com/HKUDS/RAG-Anything
- VoyageAI 임베딩(Phase 4 질의 단계 참고): https://docs.voyageai.com/docs/embeddings

## 다음 토픽

→ [문서 Data Contract — stable ID·version·source span·provenance](../04-document-data-contract/lesson.md)
