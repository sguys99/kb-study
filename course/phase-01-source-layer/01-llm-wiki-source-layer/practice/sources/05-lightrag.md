# LightRAG

LightRAG는 2024년 홍콩대학교(HKUDS) 연구진이 공개한 GraphRAG 프레임워크다.
Microsoft GraphRAG의 무거운 인덱싱 비용을 줄이려고, 그래프 인덱스와 벡터 인덱스를 함께 쓰는 가벼운 구조를 택했다.

LightRAG는 다섯 가지 쿼리 모드를 제공한다: naive, local, global, hybrid, mix. 기본은 mix다.
local은 가까운 이웃 중심, global은 전체 구조 중심이며, mix는 둘을 합친다.

LightRAG는 이 과정의 메인 프레임워크다. Microsoft GraphRAG와 같은 문제를 풀지만 비용 설계가 다르다.
