# Corrective RAG(CRAG)

Corrective RAG(CRAG)는 2024년 Yan 등이 제안했다.
검색 결과의 품질을 retrieval evaluator로 채점하고, 점수가 낮으면 웹 검색으로 보강하거나 폐기한다.

CRAG의 retrieval evaluator는 Self-RAG의 자기평가 아이디어를 검색 품질 보정으로 발전시켰다.
두 기법 모두 "검색이 항상 옳지는 않다"는 같은 전제에서 출발한다.

CRAG는 경량 평가자를 쓰기 때문에 추가 비용이 작은 편이다.
