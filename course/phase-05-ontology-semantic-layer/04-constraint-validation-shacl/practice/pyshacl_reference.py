"""
pyshacl_reference.py — (선택/참고) 같은 domain/range 제약을 진짜 SHACL 로 거는 예시

★ 이 파일은 "실무 확장" 참고용이다. 메인은 rule_engine.py(경량 엔진)다.
   pyshacl 은 RDF 로 변환해야 돌아가고 설치가 무겁다(requirements.txt 에서 주석 처리).
   실제 RDF/트리플 스토어를 쓰는 팀이 표준 SHACL 로 넘어갈 때 이 형태가 된다.

실행하려면:
   pip install "pyshacl>=0.26" "rdflib>=7.0"
   python pyshacl_reference.py

핵심 대응(경량 엔진 ↔ 표준 SHACL):
   shapes.yaml 의 RelationShape(subject_class/object_class)
     ↔ sh:NodeShape + sh:property + sh:path + sh:class
   경량 엔진의 RejectReason
     ↔ pyshacl 의 Validation Report(sh:result, sh:resultMessage)
"""

from __future__ import annotations

# SHACL Shapes 를 Turtle 로 선언한다. USES 는 domain=Method, range=Dataset.
SHAPES_TTL = """
@prefix sh:  <http://www.w3.org/ns/shacl#> .
@prefix ex:  <http://example.org/kb#> .
@prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .

# Method 노드에 대한 NodeShape: USES 로 나가는 엣지의 대상(range)은 Dataset 이어야 한다.
ex:MethodShape a sh:NodeShape ;
    sh:targetClass ex:Method ;
    sh:property [
        sh:path ex:USES ;
        sh:class ex:Dataset ;            # range 공리
        sh:message "USES 의 대상은 Dataset 이어야 한다(range 위반)" ;
        sh:severity sh:Violation ;
    ] .
"""

# 검증 대상 데이터. popqa(Dataset) 는 정상, self-rag(Method)->crag(Method) USES 는 range 위반.
DATA_TTL = """
@prefix ex: <http://example.org/kb#> .

ex:self-rag a ex:Method ;
    ex:USES ex:popqa ;      # 정상: 대상이 Dataset
    ex:USES ex:crag .       # 위반: 대상이 Method

ex:popqa a ex:Dataset .
ex:crag  a ex:Method .
"""


def main() -> None:
    try:
        from pyshacl import validate  # type: ignore
    except ImportError:
        print("pyshacl 미설치. 이 파일은 참고용이다.")
        print("설치: pip install \"pyshacl>=0.26\" \"rdflib>=7.0\"")
        print("메인 경량 엔진은 rule_engine.py 를 실행하라.")
        return

    conforms, _graph, text = validate(
        data_graph=DATA_TTL,
        shacl_graph=SHAPES_TTL,
        data_graph_format="turtle",
        shacl_graph_format="turtle",
        inference="none",
    )
    print(f"conforms(모든 제약 통과 여부): {conforms}")
    print("== pyshacl Validation Report ==")
    print(text)
    # self-rag -USES-> crag(Method) 가 range 위반이라 conforms 는 False 여야 한다.
    assert conforms is False, "range 위반을 잡지 못했다"
    print("[assert] pyshacl 이 range 위반을 잡았다")


if __name__ == "__main__":
    main()
