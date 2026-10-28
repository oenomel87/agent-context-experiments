# Actual multi-turn sessions vs separated judges

주 연구의 공개 코드·합성 데이터·익명화 관측이다. 공통 기준선210회, 단일440회, 판정 분리440회로 총1,090회이며 분석440개와판정650개를 포함한다.

- [실험 설계](PROTOCOL.md)
- [세션 흐름](review/turn-flow.md)
- [전체 관측표](published/observations.jsonl)
- [보고된 최종 집계](published/reported-summary.json)
- [집계된 로컬 검증 결과](published/verification-summary.json)
- [그래프](published/native-comparison.png)

공개 관측의 thread_id와 turn_id는 새로 부여한 별칭이다. 실제 공급자 ID, 개인 경로, 초기 개인 지침, 원본 SDK rollout은 포함하지 않는다. 별칭을 통해 기록상 세션별 턴 수를 재계산할 수 있지만 공개 파일만으로 공급자 측 실제 대화 원본을 독립적으로 입증할 수는 없다.

기존 결과의 산술 재검산은 저장소 루트에서 `python3 tools/recompute.py`로 수행한다. 새 모델 호출은 필요하지 않다. 설계 파일의 actual_model_calls=0은 작성 당시 상태이며 실제 완료 관측과 구분한다.

`src/`는 실험에 사용한 동결 코드의 공개용 이식본이다. 수정 범위는 저장소 내부 경로와 라이브 호출 opt-in 등으로, 원문·루브릭·관측값은 바꾸지 않았다. 원래 보고기의 cachewrite/total_tokens 필드와 분석 플래그 표시 한계는 [공개·재현 안내](../docs/PUBLICATION.md)에 기록했다.

`data/source/`에는 재생성에 필요한 합성 자료만 들어 있다. `build_design.py`와 `validate_design.py`는 모델을 호출하지 않는다. `AUXILIARY.md` 및 auxiliary plan은 실행하지 않은 보조 설계이며 관측 자료가 아니다.

라이브 재실행은 [설치·실행 안내](../docs/REPRODUCIBILITY.md)를 따른다. 새 결과와 실행 로그는 runs/ 아래에 생성되며 공개 저장소에는 포함하지 않는다.
