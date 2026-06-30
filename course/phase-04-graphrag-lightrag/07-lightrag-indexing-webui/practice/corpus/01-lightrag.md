# LightRAG 개요 (샘플 코퍼스)

> 이 디렉토리는 인덱싱을 바로 시험해 볼 수 있는 최소 샘플이다.
> 실제 학습에서는 Phase 1 산출물(러닝 코퍼스: arXiv RAG/GraphRAG 논문 + 프레임워크 docs)을
> CORPUS_DIR 로 지정해 쓴다. 여기 3개 파일은 멀티홉·전체요약 질문이 걸리도록 일부러 엮어 두었다.

LightRAG는 HKUDS가 공개한 GraphRAG 프레임워크다. 한 번 인덱싱하면 지식그래프(Knowledge Graph)와
벡터 저장소를 같은 working_dir 아래 함께 쌓고, 그 위에서 다섯 가지 쿼리 모드로 검색한다.

다섯 모드는 naive, local, global, hybrid, mix 다. naive는 KG 없이 텍스트 청크만 벡터검색하는
전통 RAG이고, local은 엔티티 중심으로 이웃을 정밀 매칭한다. global은 커뮤니티 요약을 모아 거시
주제를 조망한다. hybrid는 local과 global을 병합하고, mix는 KG 검색과 vector 검색을 통합한다.

LightRAG는 임베딩으로 VoyageAI voyage-3.5 를, LLM으로 Claude 를 쓸 수 있다. 저장 백엔드는
기본 파일 기반에서 Neo4j 로 교체할 수 있다.
