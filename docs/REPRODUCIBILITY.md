# 재현 범위

## 공개 관측 재계산

Python 표준 라이브러리만 필요하다. 저장소 루트에서 실행한다.

```sh
python3 tools/recompute.py
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s experiments/homogeneous/tests -v
python3 -m unittest discover -s experiments/alternating/tests -v
python3 tools/check_publication.py
```

`build/recomputed-summary.json`은 원시 공개 관측에서 새로 계산한다. `reports/recomputed-summary.json`은 게시 시 검산한 결과다. 각 실험의 `reported-summary.json`은 로컬의 별도 검증된 집계에서 내보낸 비교 기준이다. 단건 I는 동질 기록에서 가져와 교대 계산에 연결하며 전체 관측 수에서는 한 번만 센다.

두 실험의 테스트는 별도 Python 프로세스로 실행한다. 같은 이름의 모듈·테스트가 있으므로 한 프로세스에서 두 테스트 경로를 합쳐 호출하지 않는다. 가상 어댑터 테스트이며 실제 모델 응답과 섞이지 않는다.

## 공개 코드의 역할

`experiments/*/src`는 실제 실험의 역할 계약·실행기·보고기·감사 코드다. 공개본에서는 backend 경로와 라이브 호출 opt-in만 이식했다. 역할 지침·루브릭·출력 스키마·관측 점수는 변경하지 않았다. 계획의 실행 상태 메타데이터만 공개 시점에 갱신했다.

**공개본은 새 라이브 실험을 즉시 실행하는 배포 패키지가 아니다.** 자동 실행 supervisor, 개인 경로에 묶인 복구 래퍼, 원본 preflight 증거와 run snapshots는 제외했다. `run_experiment.py`에는 사전 점검 증거가 필요한 실행 제약이 그대로 남아 있다. 공개 검사에서 이 제약을 우회해 서비스를 호출하지 않는다. `EXPERIMENT_ENABLE_LIVE=1`도 단독으로 검증된 실행 환경을 만들어 주지 않는다.

backend에는 원래 SDK/CLI0.159.3 연결 코드와 의존성 목록을 보존했다. 검증한 원래 환경은 macOS/Python3.14/Node.js와 소유자의 기존 Codex ChatGPT 로그인이었다. 해당 모델에 대한 타 계정 접근이나 Linux/Windows 권한 격리는 보장하지 않는다. 새 모델 호출의 검증이나 모델 자동 대체는 수행하지 않았다.

## 완전히 재현할 수 없는 항목

공급자 원본 대화, 개인/관리 초기 지침, 로그인 캐시, 실제 공급자 세션 ID는 공개하지 않는다. 공개 별칭으로 원래 세션의 관계는 볼 수 있지만 원본 공급자 로그의 독립 인증은 아니다. 모델의 비결정적 출력, 서버 측 변경, 캐시·실행 시각까지 동일하게 재현한다고 주장하지 않는다.

기술 점검9건, 중단으로 제외된 추가 시도9건은 본 관측 밖의 원장에 있다. 제외된 완료3개 응답은 별도 파일에 보존했다. 미기록6건 중1건의 SDK 완료·사용량 흔적만 남았고5건은 사용량 미상이다. 교대 시간 초과1건도 사용량 미상이다. 관측된 토큰 합계는 완전한 청구액이 아니다.
