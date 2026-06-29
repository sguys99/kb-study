# Self-RAG

Self-RAG는 2023년 Asai 등이 발표한 기법이다. 모델이 스스로 "지금 검색이 필요한가"를 판단하고,
검색해 온 문서가 쓸 만한지 reflection token으로 자기 평가한다.

Self-RAG는 표준 RAG의 약점, 즉 불필요한 검색과 근거 없는 생성을 줄이려 한다.
이 자기평가 아이디어는 뒤에 나온 CRAG의 retrieval evaluator와 문제의식이 닿아 있다.

Asai는 워싱턴 대학에서 이 연구를 진행했다.
