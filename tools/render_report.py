"""Render the public synthesis from all exported observations; no model calls."""
import json
from pathlib import Path
from recompute import ROOT,recompute
D=recompute(ROOT/'reports/recomputed-summary.json');f=lambda x:f'{x:.2f}' if x is not None else '—';sg=lambda x:f'{x:+.2f}' if x is not None else '—'
labels={'S_warm':'단일·관대만','S_cool':'단일·엄격만','M_warm':'B·관대만','M_cool':'B·엄격만','S_warm_first':'단일·교대 관대시작','S_cool_first':'단일·교대 엄격시작','M_warm_first':'B·교대 관대시작','M_cool_first':'B·교대 엄격시작'}
L=['# 수정된 두 실험의 종합 결과','', '**확인된 것은 점수의 맥락 의존성 차이다.** 단일 S는 같은 중립 글에서도 앞선 이력에 따라 점수가 달랐고, 매번 현재 원문만 받는 B는 단건 기준선에 가까웠다. 단일에서 동질 조건 간 격차1.70점과 교대 시작 순서 간 격차의 절댓값0.50점이 관측됐다. 교대에서도 기준선 대비 상승과 현재 글 유형별 변화가 남았다.','', '단건 기준선은9.00점(n=10, SD0.00)이며, 글의 논증 품질을0–12점으로 채점한다. 사람의 성과나 정확도를 뜻하지 않는다. 모든 사례는 합성이다.','', '## 동일 중립 글: 평균·분포·기준선 대비','', '| 이력과 구조 | n | 평균 | 표본 SD | 단건 대비 Δ | 실제 점수 분포 |','|---|---:|---:|---:|---:|---|']
for name in ['homogeneous','alternating']:
 for k,c in D[name]['cells'].items():
  v=c['neutral'];freq=', '.join(f'{x}점×{n}' for x,n in v['frequencies'].items());L.append(f"| {labels[k]} | {v['n']} | {f(v['mean'])} | {f(v['sd'])} | {sg(c['neutral_delta']['mean'])} | {freq} |")
L+=['','교대 관대시작은 마지막 이력이 엄격이고, 엄격시작은 마지막 이력이 관대다. 중립 글은 그 다음에 평가했다.','', '![분포 비교](neutral-comparison.png)','', '## 대응 반복과 결측','', 'G는 동질에서 관대−엄격, 교대에서 관대시작−엄격시작이다. 비교 대상의 의미가 다르므로 두 값을 이용해 인과적 개선율을 계산하지 않는다. D는 네 조건이 모두 있는 같은 반복에서 G_S−G_B를 계산한다.','', '| 실험 | 대비 | n | 평균 차이 | SD | 평균 절대 차이 |','|---|---|---:|---:|---:|---:|']
for name in ['homogeneous','alternating']:
 if name=='alternating':L+=['| 실험 | 대비 | n | 평균 차이 | SD | 평균 절대 차이 |','|---|---|---:|---:|---:|---:|']
 for k in ['S','M','D']:
  x=D[name]['contrasts'][k]['stats'];L.append(f"| {name} | {'G_'+k if k!='D' else 'D'} | {x['n']} | {sg(x['mean'])} | {f(x['sd'])} | {f(x['mean_absolute'])} |")
 c=D[name]['contrasts'];L+=['',f"{name} 공통 완료 반복 {c['common_replicates']}: G_S={sg(c['S']['common_stats']['mean'])}, G_B={sg(c['M']['common_stats']['mean'])}.",'']
L+=['동질에서 단일의 관대−엄격 차이는+1.70점, 교대의 관대시작−엄격시작 차이는−0.50점이었다. 교대에서 단일은 두 조건 모두 단건보다 높았다(+0.90/+1.40). 최근 글의 영향과 양쪽 이력의 상쇄가 가능한 설명이지만, 시작·끝 순서·자기 평가 이력을 따로 조작하지 않아 원인을 확정하지 않는다.','', '## 누적 중 현재 글의 변화','', '동일 글·동일 반복의 단건과 뺀 Δ다. 글 유형 간 원점수 차이가 아니다. 각 호출을 독립 표본으로 보지 않는다.','', '| 실험·구조 | 현재 글 성격 | n | 평균 Δ | SD | 평균 절대 Δ |','|---|---|---:|---:|---:|---:|']
for name in ['homogeneous','alternating']:
 for arm in ['S','M']:
  for tone in ['warm','cool']:
   x=D[name]['pooled_current_delta_by_tone'][arm+'_'+tone];L.append(f"| {name} · {arm} | {'관대' if tone=='warm' else '엄격'} | {x['n']} | {sg(x['mean'])} | {f(x['sd'])} | {f(x['mean_absolute'])} |")
L+=['','교대의 단일 S는 관대한 현재 글−0.17점, 엄격한 현재 글+1.48점이었다. 새 B는−0.05/+0.12점이었다. 따라서 마지막 중립 글만 보면 누적 중 글 유형별로 다르게 바뀐 채점 경향을 놓친다. 다만 현재 글과 직전 글의 유형이 교대 규칙으로 연결되므로 이 표만으로 두 효과를 분리할 수 없다.','', '## 누적 단계별 Δ','', '중립 글을 단계마다 평가한 값이 아니라 각 단계의 현재 글에 대한 기준선 차이다. 괄호는 해당 단계의 유효 관측 수다.']
for name in ['homogeneous','alternating']:
 keys=list(D[name]['cells']);L+=['',f'### {name}','','| 단계 | '+' | '.join(labels[k] for k in keys)+' |','|---:|---:|---:|---:|---:|']
 for i in range(1,11):L.append('| '+str(i)+' | '+' | '.join(sg(D[name]['cells'][k]['position_delta'][str(i)]['mean'])+f" (n={D[name]['cells'][k]['position_delta'][str(i)]['n']})" for k in keys)+' |')
L+=['','## 점수 안정성과 전달 신뢰성','', '동질에서 A의 ID 누락3건이, 교대에서는 ID 누락2건과90초 시간 초과1건이 발생했다. 잘못된 ID는 현재 ID의 끝부분을 누락한 것으로 이전 ID를 재사용한 사례는 아니다. 이 오류를 맥락 간섭 때문이라고 단정할 수 없다. 시간 초과는 응답 내용의 판단 오류와 구분한다.','', '| 실험 | 배정된 사용자 요청 | 반환 완료 | 완주한 A 대화 |','|---|---:|---:|---:|','| 동질 | 220 | 211 | 17/20 |','| 교대 | 220 | 213 | 17/20 |','', '아래는 중립 글의 채점 완료에 더해 A의 반환까지 성공한 결과다.','', '| 조건 | n | 중립 평균 |','|---|---:|---:|']
for name in ['homogeneous','alternating']:
 for k,c in D[name]['cells'].items():
  if k.startswith('M_'):x=c['neutral_delivered'];L.append(f"| {labels[k]} | {x['n']} | {f(x['mean'])} |")
L+=['','B의 채점은 유효해도 사용자에게 반환되지 않은 사례를 전체 서비스 성공으로 세지 않았다. 실패 이후 의존 작업은 차단했으며 누락 점수를0으로 대체하지 않았다. 교대에서 실패3건이 모두 관대시작 조건에 발생했으므로 조건별 n과 공통 완료 반복을 함께 봐야 한다.','', '## 사용량과 복구','', '| 실험·역할 | 시도 | 입력 토큰 | 캐시 입력(입력의 일부) | 출력 토큰 | 사용량 미상 시도 |','|---|---:|---:|---:|---:|---:|']
for name in ['homogeneous','alternating']:
 for k,u in D[name]['usage_by_role'].items():
  if name=='alternating' and k.startswith('I/'):continue
  L.append(f"| {name} · {k} | {u['attempts']} | {u.get('input_tokens',0):,} | {u.get('cached_input_tokens',0):,} | {u.get('output_tokens',0):,} | {u.get('unknown_usage_attempts',0)} |")
L+=['','토큰은 관측된 값의 합이며 미상 사용량은0이 아니다. 캐시 입력은 입력의 부분집합이다. 기술 점검9건과 동질 중단 복구에서 제외된 추가 시도9건은 위 표 밖의 [실행 원장](execution-accounting.json)에 별도 기록한다. 추가 시도 중 알려진 사용량은 입력23,654/캐시12,928/출력1,292토큰이며5건은 미상이다. 전체 실험의 서비스 호출 시도는 기술·복구를 포함해1,954건이고, 사용량 미상 시도는 총6건이다. 이는 청구액 확정이나 동일 비용 비교가 아니다.','', '## 확인된 사실과 미검증 가설','', '**확인된 사실:** 이 자료와 모델 설정에서 실제 대화가 누적된 S는 단건과 다른 점수를 냈고, 그 차이는 이력 구성·순서·현재 글 유형에 따라 달랐다. 새 B는 단건에 가까웠다. 평가 입력 경계와 실제 세션 연속성은 로컬에서 검증했다. 멀티 구조에는 별도의 전달 실패가 있었다.','', '**지지되는 해석:** 과제에 불필요한 이전 평가 이력을 원문 분석 단계부터 분리하면 점수의 이력 의존성을 줄일 수 있다. 그러나 B와 I는 입력을 같게 설계했으므로 이는 맥락 격리의 검증이다. 단일 시스템 안에서 새 평가 세션을 생성하는 구현도 같은 경계를 만들 수 있다.','', '**미검증:** 인간 정답 대비 정확도, 일반적 멀티 에이전트 우월성, 순수한 긍정/부정 표현 효과, 숫자100/70의 단독 효과, 자기 점수와 평가 이유 각각의 효과, 최근성·상쇄·초기성의 분리, 다른 모델·과제·긴 대화로의 일반화다. 이력 정보가 정답에 필요한 작업도 다루지 않았다.','', '두 실험은 다른 시각에 실행됐고 단건 기준선을 공유한다. 순서 반복 수는 작고, 결측은 배정 후 발생했다. 모델 내부 상태나 서비스 변경까지 통제했다고 주장하지 않는다. 인용문 자동 경고는 동질7개 응답9개 구절, 교대11개 응답11개 구절로 보존했으며 내용 정확성은 별도 사람 검토 대상이다.','', '## 증거와 재계산','', '- [공개 집계 JSON](recomputed-summary.json)','- [원본 상태·복구 원장](execution-accounting.json)','- [동질 관측](../experiments/homogeneous/observations.jsonl) · [교대 새 관측](../experiments/alternating/observations.jsonl)','- [실험 방법](../docs/METHODS.md) · [공개 증거의 한계](../docs/PUBLICATION.md)','', '이 결과는 맥락 관리와 전달 신뢰성을 분리해 평가해야 함을 보여주는 제한된 실험적 근거다.']
(ROOT/'reports/RESULTS.md').write_text('\n'.join(L)+'\n');print('Rendered reports/RESULTS.md and reports/recomputed-summary.json')
