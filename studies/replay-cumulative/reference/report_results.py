"""Offline descriptive analysis; never calls a model or imputes missing scores."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

DIMENSIONS = ('total', 'claim_clarity', 'support_linkage', 'qualification')

def stats(values):
    v = list(values)
    return {'n': len(v), 'mean': statistics.mean(v) if v else None,
            'median': statistics.median(v) if v else None,
            'min': min(v) if v else None, 'max': max(v) if v else None,
            'sd': statistics.stdev(v) if len(v) > 1 else None, 'values': v}

def score(record):
    if not record or record.get('status') not in ('success', 'completed', 'succeeded'):
        return None
    response = record.get('response') or {}
    if isinstance(response, str):
        try: response = json.loads(response)
        except (ValueError, TypeError): return None
    s = response.get('scores', record.get('scores'))
    if not isinstance(s, dict) or any(type(s.get(d)) is not int or not 0 <= s[d] <= 4 for d in DIMENSIONS[1:]):
        return None
    return {**{d: s[d] for d in DIMENSIONS[1:]}, 'total': sum(s[d] for d in DIMENSIONS[1:])}

def build_summary(run_dir):
    run = Path(run_dir)
    plan = json.loads((run / 'snapshots/data/plan.json').read_text())
    jobs = plan['jobs']
    records = {p.stem: json.loads(p.read_text()) for p in sorted((run / 'records').glob('*.json'))}
    scores = {j['job_id']: score(records.get(j['job_id'])) for j in jobs}
    curves = {'probe': {}, 'sequential': {}, 'paired_tone': {}}
    baselines = defaultdict(list)
    for j in jobs:
        s = scores[j['job_id']]
        if j['kind'] == 'baseline' and s is not None:
            baselines[j['submission_id']].append({'replicate': j['replicate'], 'job_id': j['job_id'], 'scores': s})
        if j['kind'] not in ('probe', 'sequential'): continue
        kind, tone, r = j['kind'], j['tone'], str(j['replicate'])
        k = j['depth'] if kind == 'probe' else j['position']
        curve = curves[kind].setdefault(tone, {}).setdefault(r, {})
        b = scores.get(j.get('baseline_job_id'))
        curve[str(k)] = {'job_id': j['job_id'], 'baseline_job_id': j.get('baseline_job_id'),
                         'raw': s, 'delta': {d: s[d]-b[d] for d in DIMENSIONS} if s is not None and b is not None else None}
        if kind == 'probe':
            curve['0'] = {'job_id': j.get('baseline_job_id'), 'raw': b,
                          'delta': {d: 0 for d in DIMENSIONS} if b is not None else None}
    reps = sorted({str(j['replicate']) for j in jobs}, key=int)
    for r in reps:
        curves['paired_tone'][r] = {}
        for k in range(1, 11):
            w = curves['probe'].get('warm', {}).get(r, {}).get(str(k), {}).get('raw')
            c = curves['probe'].get('cool', {}).get(r, {}).get(str(k), {}).get('raw')
            curves['paired_tone'][r][str(k)] = {d: w[d]-c[d] for d in DIMENSIONS} if w is not None and c is not None else None
    depth = {}
    for kind in ('probe', 'sequential'):
        depth[kind] = {}
        for tone in ('warm', 'cool'):
            depth[kind][tone] = {}
            for d in DIMENSIONS:
                depth[kind][tone][d] = {str(k): {field: stats(c[str(k)][field][d] for c in curves[kind].get(tone, {}).values() if c.get(str(k), {}).get(field) is not None) for field in ('raw', 'delta')} for k in range(0 if kind == 'probe' else 1, 11)}
    depth['paired_tone'] = {d: {str(k): stats(c[str(k)][d] for c in curves['paired_tone'].values() if c.get(str(k)) is not None) for k in range(1,11)} for d in DIMENSIONS}
    trajectory = {}
    sources = {tone: {r: {k: p['delta'] for k,p in c.items()} for r,c in curves['probe'].get(tone, {}).items()} for tone in ('warm','cool')}
    sources['warm_minus_cool'] = curves['paired_tone']
    for label, source in sources.items():
        trajectory[label] = {}
        for d in DIMENSIONS:
            per_rep = {}
            for r,c in source.items():
                if all(c.get(str(k)) is not None for k in range(1,11)):
                    per_rep[r] = {'mean_k1_10': statistics.mean(c[str(k)][d] for k in range(1,11)), 'late_minus_early': statistics.mean(c[str(k)][d] for k in (8,9,10))-statistics.mean(c[str(k)][d] for k in (1,2,3))}
            trajectory[label][d] = {'per_replicate': per_rep, 'excluded_replicates': [r for r in reps if r not in per_rep], **{m: stats(v[m] for v in per_rep.values()) for m in ('mean_k1_10','late_minus_early')}}
    planned_ids = {j['job_id'] for j in jobs}
    used_records = [records[j] for j in planned_ids if j in records]
    no_call_blocked = sum(r.get('status') == 'blocked' for r in used_records)
    attempted = [r for r in used_records if r.get('status') not in ('blocked', 'missing', 'pending')]
    unknown_attempted = sum(not r.get('usage') for r in attempted)
    usage_keys = sorted({k for r in used_records for k in (r.get('usage') or {})})
    usage = {k: {'known_sum': sum(r['usage'][k] for r in used_records if isinstance((r.get('usage') or {}).get(k), (int,float))), 'known_records': sum(isinstance((r.get('usage') or {}).get(k), (int,float)) for r in used_records), 'unknown_records': len(jobs)-sum(isinstance((r.get('usage') or {}).get(k), (int,float)) for r in used_records)} for k in usage_keys}
    return {'planned': len(jobs), 'counts': dict(Counter(records.get(j['job_id'], {}).get('status','missing') for j in jobs)), 'valid_scores': sum(v is not None for v in scores.values()), 'unplanned_record_ids': sorted(set(records)-planned_ids), 'usage': usage, 'usage_no_call_blocked': no_call_blocked, 'usage_unknown_attempted': unknown_attempted, 'usage_unrecorded_assignments': len(jobs)-len(used_records), 'usage_missing_records': sum(not records.get(j['job_id'],{}).get('usage') for j in jobs), 'baseline': {sid: {'observations': obs, 'dimensions': {d: stats(o['scores'][d] for o in obs) for d in DIMENSIONS}} for sid,obs in baselines.items()}, 'depth': depth, 'curves': curves, 'trajectory_summary': trajectory}

def fmt(s):
    if not s['n']: return '0 / —'
    return f"{s['n']} / {s['mean']:.3f} / {s['median']:.3f} / [{s['min']:.3f}, {s['max']:.3f}]"

def write_report(run_dir, output_dir=None):
    run = Path(run_dir).resolve(); out = Path(output_dir).resolve() if output_dir else run / 'report'
    out.mkdir(parents=True, exist_ok=True)
    result = build_summary(run)
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 누적 평가 관측 보고서', '', f"계획 {result['planned']}개, 유효 점수 {result['valid_scores']}개. 상태: {json.dumps(result['counts'],ensure_ascii=False)}.", '', '결측·실패·차단은 0점으로 대체하지 않았다. 610개 배정은 공유 기준선·글·중첩 이력 때문에 독립 표본이 아니다. 유의성 검정과 p값을 사용하지 않는다. k=0 차이는 정의상 0이며 Q 원점수 변동은 아래 기준선 분포로 공개한다. t=1은 이력 효과가 아니라 동일 입력 재실행 점검이다.', '', '단일 중립 글과 정서·태도 표현 묶음의 결과이며 중립 이력 대조군이 없다. 정서, 숫자 앵커링, 문맥 길이, 순서 및 서비스 시간 변화의 원인은 분리할 수 없다. 상승·하락은 정확도나 공정성 변화를 뜻하지 않는다.', '', '표 셀: n / 평균 / 중앙값 / [최소, 최대]. 원점수와 대응 차이의 유효 n은 다를 수 있다.']
    for kind in ('probe','sequential'):
        for tone in ('warm','cool'):
            for d in DIMENSIONS:
                lines += ['', f'## {kind} · {tone} · {d}', '', '| 깊이/위치 | 원점수 | 같은 반복 기준선 대비 |','|---|---|---|']
                for k,p in result['depth'][kind][tone][d].items(): lines.append(f"| {k} | {fmt(p['raw'])} | {fmt(p['delta'])} |")
    for d, rows in result['depth']['paired_tone'].items():
        lines += ['', f'## 중립 warm−cool · {d}', '', '| 깊이 | 완전 대응 차이 |','|---|---|']
        lines += [f'| {k} | {fmt(s)} |' for k,s in rows.items()]
    lines += ['', '## 완전 궤적 요약', '', 'k=1…10 모두 존재하는 반복만 포함하고 반복별 계산 후 동일 가중치 평균을 낸다. 후기−초기는 k=8…10 평균에서 k=1…3 평균을 뺀 값이다.', '', '| 비교 | 기준 | 전체 평균 | 후기−초기 | 제외 반복 |','|---|---|---|---|---|']
    for label, dims in result['trajectory_summary'].items():
        for d,s in dims.items(): lines.append(f"| {label} | {d} | {fmt(s['mean_k1_10'])} | {fmt(s['late_minus_early'])} | {s['excluded_replicates']} |")
    lines += ['', '## 단건 기준선 분포', '', '| 글 ID | 기준 | n / 평균 / 중앙값 / 범위 | 표본 SD | 관측값 |','|---|---|---|---|---|']
    for sid,b in result['baseline'].items():
        for d,s in b['dimensions'].items(): lines.append(f"| {sid} | {d} | {fmt(s)} | {s['sd']} | {s['values']} |")
    lines += ['', '## 반복별 궤적 및 사용량', '', '반복별 모든 원점수·차이·개별 요약은 [summary.json](summary.json)의 curves와 trajectory_summary.per_replicate에 공개한다. 사용량 미확인 값은 0으로 간주하지 않는다. usage_no_call_blocked는 공급자 호출 없이 차단된 기록 수, usage_unknown_attempted는 시도 기록 중 사용량 미확인 수, usage_unrecorded_assignments는 기록 없는 배정 수다. 기존 usage_missing_records 및 항목별 unknown_records는 차단·미기록을 포함한 전체 계획 배정의 미확인 범위다.', '', '```json', json.dumps({'usage':result['usage'],'usage_missing_records':result['usage_missing_records'], 'usage_no_call_blocked':result['usage_no_call_blocked'], 'usage_unknown_attempted':result['usage_unknown_attempted'], 'usage_unrecorded_assignments':result['usage_unrecorded_assignments']},ensure_ascii=False,indent=2), '```', '', '[실제 전체 평가·이유](actual-observations.md)']
    (out/'overview.md').write_text('\n'.join(lines)+'\n')
    plan = json.loads((run/'snapshots/data/plan.json').read_text())
    observations = ['# 실제 전체 평가 기록', '', '관측된 응답 전체와 이유를 그대로 공개한다. 파일이 없는 배정은 missing이다.']
    for j in plan['jobs']:
        p = run/'records'/f"{j['job_id']}.json"
        observations += ['', f"## {j['job_id']} · {j['kind']} · 반복 {j['replicate']}"]
        if p.exists():
            record=json.loads(p.read_text()); observations += ['', f'[원본 기록]({p})', '', '```json', json.dumps(record,ensure_ascii=False,indent=2), '```']
        else: observations += ['', 'missing — 실제 응답 없음.']
    (out/'actual-observations.md').write_text('\n'.join(observations)+'\n')
    return result

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('run_dir'); parser.add_argument('--output-dir')
    args=parser.parse_args(); write_report(args.run_dir,args.output_dir)
