# Microsoft GraphRAG

Microsoft GraphRAG는 2024년 Edge 등이 발표했다. 부제는 *From Local to Global*이다.
문서에서 엔티티와 관계를 뽑아 지식그래프를 만들고, 커뮤니티 탐지로 묶은 뒤 요약을 계층적으로 쌓는다.

이 방식은 표준 RAG가 못 하던 전체(global) 요약 질문에 강하다.
"이 코퍼스 전체의 핵심 주제는?" 같은 질문은 벡터 검색 몇 조각으로는 답하기 어렵다.

Microsoft GraphRAG는 커뮤니티 요약을 미리 만들어 두기 때문에 인덱싱 비용이 큰 편이다.
이 비용 문제를 가볍게 풀려는 시도가 LightRAG다.
