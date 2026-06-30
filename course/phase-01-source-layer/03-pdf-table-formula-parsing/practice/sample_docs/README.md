# 비교용 샘플 PDF 준비

저작권 때문에 PDF 자체는 저장소에 커밋하지 않는다. 아래 절차로 직접 내려받아 이 디렉토리에 둔다.

## 1) 영어 + 표·수식 PDF (arXiv 논문)

Microsoft *From Local to Global* (GraphRAG) 논문을 받는다. 02·01 코퍼스의 `04-graphrag-ms.md`가 정제한 바로 그 논문이라, 변환 단계와 위키 단계가 같은 원문으로 이어진다.

```bash
curl -L -o sample_docs/2404.16130.pdf https://arxiv.org/pdf/2404.16130
```

표와 수식이 함께 들어 있어 Docling 의 표 추출·수식 enrichment 를 확인하기 좋다.

## 2) 한국어 + 표 PDF (1건)

한국어 OCR 비교용으로 표가 들어간 한국어 기술 문서/보고서 PDF 1건을 준비한다(공공데이터 보고서, 사내 비공개 아닌 공개 문서 등). 파일명은 `sample_docs/ko_sample.pdf` 로 둔다. 스캔본이면 MinerU 의 OCR 강점을, 텍스트 PDF 면 한글 보존율을 본다.

## 3) 연결 — 01/02 코퍼스와의 관계

01·02 는 이미 정제된 Markdown 8건을 입력으로 받았다. 그 8건의 *출처가 되는 원문 PDF* 를 충실히 변환하는 단계가 03 이다. 즉 03 의 산출물(파싱된 Markdown)이 04(Data Contract)·05(chunking)의 입력이 되고, 어느 파서가 표·수식·한국어를 얼마나 보존했는지가 이후 source span·인용 품질을 좌우한다.

> 한글 보존율(`compare_parsers.py --ref-hangul N`)을 쓰려면 입력 PDF 의 한글 음절 수를 대략 알아야 한다. 정확할 필요는 없다. 세 파서를 같은 기준으로 재어 상대 차이를 보는 용도다.
