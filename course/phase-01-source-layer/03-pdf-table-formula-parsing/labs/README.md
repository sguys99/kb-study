# Lab — 같은 PDF를 세 파서로 변환하고 한 표로 비교

각 단계마다 명령과 **예상 출력**을 함께 둔다. 네 환경의 출력이 형태상 이와 비슷하면 정상이다(절대 수치는 입력 PDF·파서 버전에 따라 다르다).

작업 디렉토리는 `practice/` 기준이다.

```bash
cd course/phase-01-source-layer/03-pdf-table-formula-parsing/practice
```

---

## 1단계 — 의존 설치

```bash
pip install -r requirements.txt
# MinerU 는 별도(무거움):
uv pip install -U "mineru[all]"        # 또는 pip install -U "mineru[all]"
```

예상 출력(요약):

```
Successfully installed docling-... raganything-... pandas-...
```

MinerU 설치는 모델 메타·의존이 많아 시간이 걸린다. 설치를 건너뛰어도 나머지 단계는 돈다(해당 파서만 `missing`으로 표시됨).

## 2단계 — 샘플 PDF 준비

```bash
curl -L -o sample_docs/2404.16130.pdf https://arxiv.org/pdf/2404.16130
# 한국어 PDF 1건은 sample_docs/ko_sample.pdf 로 직접 둔다(sample_docs/README.md 참고)
```

예상 출력:

```
sample_docs/2404.16130.pdf  내려받기 완료(수 MB)
```

## 3단계 — Docling 실행

```bash
python parse_docling.py sample_docs/2404.16130.pdf --out out/docling
```

예상 출력:

```
[docling] sample_docs/2404.16130.pdf
  -> out/docling/2404.16130.md  (formula_enrichment=True)
  -> 표 4건 CSV 저장
```

확인: `out/docling/2404.16130.md` 를 열어 `| --- |` 구분선이 있는 Markdown table 이 살아 있는지, `out/docling/2404.16130.table_0.csv` 의 행·열이 맞는지 본다. 수식이 `$...$` 로 남았는지도 본다(`--no-formula` 로 끄면 수식 토큰이 거의 0).

## 4단계 — MinerU 실행

```bash
python parse_mineru.py sample_docs/ko_sample.pdf --out out/mineru
```

설치돼 있을 때 예상 출력:

```
[mineru] 실행: mineru -p sample_docs/ko_sample.pdf -o out/mineru
  ...(첫 실행 시 모델 다운로드 로그)...
  -> 산출물: out/mineru/ (Markdown/JSON)
```

CLI 미설치 시 예상 출력(죽지 않고 안내만):

```
[건너뜀] mineru CLI 가 PATH 에 없다.
  설치: uv pip install -U "mineru[all]"  (또는 pip install -U "mineru[all]")
  설치 후 다시 실행하라. 옛 magic-pdf 명령은 더 이상 권장 경로가 아니다.
```

## 5단계 — RAG-Anything 실행(파싱만)

```bash
python parse_raganything.py sample_docs/ko_sample.pdf --parser mineru --out out/raganything
```

예상 출력:

```
[raganything] parser=mineru  -> out/raganything/
  질의 단계(rag.aquery)는 Phase 4(LightRAG)에서 LLM·임베딩과 함께 다룬다.
```

`--parser docling` 으로 바꾸면 내부 파서가 Docling 으로 교체된다. RAG-Anything 은 파서를 *고르는* 계층이라는 점을 여기서 확인한다.

## 6단계 — 비교 하니스 실행

```bash
python compare_parsers.py --root out --ref-hangul 800
```

예상 출력(형태 예시 — 수치는 입력에 따라 다름):

```
                     status  table_blocks  formula_tokens  hangul_chars  hangul_ratio
parser
docling                  ok             4              12             0          0.00
mineru                   ok             3               2           812          1.02
raganything              ok             3               2           805          1.01
```

MinerU 를 설치하지 않았다면:

```
                     status  table_blocks  formula_tokens  hangul_chars  hangul_ratio
parser
docling                  ok           4.0            12.0           0.0           0.0
mineru              missing           NaN             NaN           NaN           NaN
raganything              ok           3.0             2.0         805.0          1.01
```

## 7단계 — 결과 검증(헬스체크)

- `out/docling/`·`out/mineru/`·`out/raganything/` 에 `.md` 가 각각 생겼는가.
- `compare_parsers.py` 출력이 세 행을 한 표로 보여주는가(`missing` 포함 가능).
- 영어 수식 논문에서 Docling 의 `formula_tokens` 가 0 보다 큰가(enrichment 켰을 때).
- 한국어 PDF 에서 MinerU 의 `hangul_chars` 가 Docling 보다 큰가.

위가 모두 맞으면 **완료 기준**("`python compare_parsers.py` 가 세 파서의 표 블록 수·수식 토큰 수·한국어 보존율을 한 표로 출력하고, 각 파서 산출 Markdown 이 `out/<parser>/` 에 저장")을 충족한 것이다.
