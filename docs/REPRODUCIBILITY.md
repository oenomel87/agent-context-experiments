# 재현 범위와 실행

## 모델 없이 가능한 작업

저장소 루트에서 다음 명령을 실행한다. Python 표준 라이브러리만 사용하는 공개 관측 재검산과 모의 테스트다.

```sh
python3 tools/recompute.py
python3 -m unittest discover -s native/tests -v
python3 -m unittest discover -s tests -v
python3 tools/check_publication.py
```

모든 관측을 대상으로 다시 계산한다. 점수 평균은 논증 품질이며 정답률이 아니다. 1,090개 요청은 같은 글과 이력을 공유하므로 독립 표본1,090개를 뜻하지 않는다.

## 설계 재생성

```sh
python3 native/src/build_design.py
python3 native/src/validate_design.py
```

설계는 주 실험1,090개와 실행하지 않은 보조 계획으로 구분된다. 기본 data/plan.json에는 주 실험만 포함한다. 생성기는 합성 입력과 배정을 만들며 관측표를 덮어쓰지 않는다.

## 선택적인 새 라이브 실행

이 부분은 모델 서비스에 실제 요청을 보내며 사용량을 발생시킨다. 기존 공개 결과의 재검산에는 필요 없다. 검증한 원래 환경은 macOS, Python3.14, Node.js, Codex SDK/CLI0.159.3이었다. Linux/Windows의 권한 격리 경로는 이 연구에서 검증하지 않았다.

backend/package.json, package-lock.json과 requirements.lock.txt는 원래 버전을 기록한다. 의존성 소스·바이너리와 로그인 캐시는 포함하지 않는다. 라이브 코드는 기존 Codex의 ChatGPT 로그인을 사용하며 인증정보를 저장소에 넣지 않는다. 연구 당시 gpt-6-luna가 해당 계정에서 관측됐다는 기록일 뿐, 모든 공개 계정에서 이 모델에 접근할 수 있다는 보장은 아니다. 자동으로 다른 모델을 선택하지 않는다.

원래 실행기 인터페이스를 보존한 예시:

```sh
python3 -m venv backend/.venv
. backend/.venv/bin/activate
python -m pip install -r backend/requirements.lock.txt
npm --prefix backend ci
# 자신의 Codex 계정/모델 접근을 별도로 확인한 뒤에만 설정한다.
export EXPERIMENT_ENABLE_LIVE=1
python native/src/preflight.py --output native/runs/preflight-20261025-v1
python native/src/launch_main.py
```

디렉터리 이름의 날짜는 보존한 실행 라벨이다. 이미 같은 출력 폴더가 있으면 덮어쓰기 대신 중단한다. 실제 SDK 세션의 부분 중단을 JSON 재생으로 대체하지 않는다. 기술 점검과 본 실행이 생성하는 runs/는 gitignore 대상이다.

이 공개본 준비 과정에서는 의존성을 새로 설치하거나 라이브 모델을 다시 호출하지 않았다. 실행 환경에서 초기 개인/관리 지침이 추가될 수 있으며, 원래 환경의 개인 지침 원문은 공개하지 않았다. 동일한 확률적 모델 출력의 재현이나 환경 지침까지의 완전한 동일성은 보장하지 않는다.
