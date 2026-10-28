"""Offline descriptive reporting for the native main four-condition experiment."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean

LABELS = {'S2/warm': '단일 세션·관대', 'S2/cool': '단일 세션·엄격',
          'M2/warm': '판정 분리·관대', 'M2/cool': '판정 분리·엄격'}
SUCCESS = {'success', 'succeeded', 'completed', 'ok'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def score(record):
    if record.get('status') not in SUCCESS:
        return None
    response = record.get('response', {})
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return None
    values = response.get('scores') if isinstance(response, dict) else None
    if not isinstance(values, dict) or len(values) != 3:
        return None
    if any(type(v) not in (int, float) or not 0 <= v <= 4 for v in values.values()):
        return None
    return dict(values, total=sum(values.values()))


def distribution(rows):
    """Keep every observation and per-dimension denominators, including empty data."""
    dimensions = sorted({key for row in rows for key in row['scores']})
    return {'n': len(rows), 'means': {key: mean([r['scores'][key] for r in rows if key in r['scores']])
            for key in dimensions}, 'per_observation': rows}


def difference(a, b):
    if a is None or b is None or set(a) != set(b):
        return None
    return {key: a[key] - b[key] for key in a}


def paired_summary(rows):
    result = distribution(rows)
    result['mean_absolute'] = {key: mean(abs(r['scores'][key]) for r in rows)
                               for key in result['means']}
    return result


def report(run):
    run = Path(run)
    plan_path = run / 'snapshots/data/plan.json'
    if not plan_path.exists():
        raise FileNotFoundError('Frozen run/snapshots/data/plan.json is required')
    plan = read_json(plan_path)
    jobs = {j['job_id']: j for j in plan['jobs']}
    if any(j['arm'] not in {'I', 'S2', 'M2'} for j in jobs.values()):
        raise ValueError('Auxiliary jobs must not enter the main report')
    paths = [run / n for n in ('results.jsonl', 'records.jsonl', 'responses.jsonl')]
    existing = [p for p in paths if p.exists()]
    if len(existing) > 1:
        raise ValueError('Ambiguous record files')
    record_files = sorted((run / 'records').glob('*.json'))
    if record_files and existing:
        raise ValueError('Ambiguous record sources')
    records = ([read_json(p) for p in record_files] if record_files else
               [json.loads(line) for line in existing[0].read_text().splitlines() if line.strip()] if existing else [])
    if any(r.get('job_id') not in jobs for r in records):
        raise ValueError('Unknown/auxiliary record job_id')
    counts = Counter(r['job_id'] for r in records)
    if any(n > 1 for n in counts.values()):
        raise ValueError('Multiple attempts require an explicit selection policy; refusing score selection')
    for r in records:
        if any(field in r and r[field] != jobs[r['job_id']].get(field) for field in ('arm', 'tone', 'stage', 'replicate', 'position')):
            raise ValueError('Record metadata differs from frozen plan')
    actual = {r['job_id']: dict(jobs[r['job_id']], **r) for r in records}
    scored = {key: score(r) for key, r in actual.items() if r['stage'] in {'judge', 'probe'}}
    cells = {}
    for cell, label in LABELS.items():
        arm, tone = cell.split('/')
        selected = [r for r in actual.values() if r['arm'] == arm and r.get('tone') == tone]
        def grade_rows(stage):
            return [{'job_id': r['job_id'], 'replicate': r['replicate'], 'position': r.get('position'),
                     'submission_id': r['submission_id'], 'scores': scored[r['job_id']]}
                    for r in selected if r['stage'] == stage and scored.get(r['job_id']) is not None]
        cells[cell] = {'label': label, 'planned_calls': sum(j['arm'] == arm and j.get('tone') == tone for j in jobs.values()),
                       'observed_records': len(selected), 'current_grades': distribution(grade_rows('judge')),
                       'neutral_probe': distribution(grade_rows('probe'))}
    probes = {(j['arm'], j.get('tone'), j['replicate']): scored.get(key)
              for key, j in jobs.items() if j['stage'] == 'probe'}
    primary = {name: [] for name in ('G_S', 'G_M', 'D')}
    for rep in sorted({j['replicate'] for j in jobs.values()}):
        s = difference(probes.get(('S2', 'warm', rep)), probes.get(('S2', 'cool', rep)))
        m = difference(probes.get(('M2', 'warm', rep)), probes.get(('M2', 'cool', rep)))
        for name, value in [('G_S', s), ('G_M', m), ('D', difference(s, m))]:
            if value is not None:
                primary[name].append({'replicate': rep, 'scores': value})
    baseline = defaultdict(list)
    for job in jobs.values():
        if job['arm'] == 'I':
            baseline[job['submission_id']]  # Include missing text distributions explicitly.
    contrasts = {'neutral_minus_I': defaultdict(list), 'current_minus_I': defaultdict(list), 'S2_minus_M2': []}
    for key, job in jobs.items():
        value = scored.get(key)
        if value is None:
            continue
        row = {'job_id': key, 'replicate': job['replicate'], 'position': job.get('position'), 'scores': value}
        if job['arm'] == 'I':
            baseline[job['submission_id']].append(row)
            continue
        delta = difference(value, scored.get(job.get('baseline_job_id')))
        if delta is not None:
            contrasts['neutral_minus_I' if job['stage'] == 'probe' else 'current_minus_I'][job['arm']+'/'+job['tone']].append(
                dict(row, scores=delta, baseline_job_id=job['baseline_job_id'], submission_id=job['submission_id']))
        if job['arm'] == 'S2':
            matches = [other for other in jobs.values() if other['arm'] == 'M2' and other['stage'] == job['stage']
                       and all(other.get(f) == job.get(f) for f in ('tone', 'replicate', 'position', 'submission_id'))]
            if len(matches) == 1:
                delta = difference(value, scored.get(matches[0]['job_id']))
                if delta is not None:
                    contrasts['S2_minus_M2'].append(dict(row, scores=delta, tone=job['tone'], stage=job['stage'], paired_job_id=matches[0]['job_id']))
    usage = {}
    chargeable = [r for r in actual.values() if r.get('status') != 'blocked']
    for metric in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'cachewrite', 'total_tokens'):
        values = [(r.get('usage') or {}).get(metric) for r in chargeable]
        known = [v for v in values if type(v) in (int, float)]
        usage[metric] = {'known_sum': sum(known), 'known_turns': len(known), 'unknown_turns': len(values)-len(known)}
    threads = defaultdict(list)
    for r in actual.values():
        thread = r.get('thread_id') or r.get('native_thread_id')
        if thread:
            threads[thread].append(r['job_id'])
    logical = Counter(j['session_key'] for j in jobs.values())
    result = {'scope': 'main_four_conditions', 'planned_calls': len(jobs), 'observed_records': len(records),
              'statuses': dict(Counter(r.get('status', 'unknown') for r in records)),
              'missing_records': len(jobs)-len(records), 'valid_grades': sum(v is not None for v in scored.values()),
              'cells': cells, 'primary': {k: paired_summary(v) for k, v in primary.items()},
              'baseline_per_text': {k: distribution(v) for k, v in baseline.items()},
              'contrasts': {k: paired_summary(v) if isinstance(v, list) else {c: paired_summary(rows) for c, rows in v.items()} for k, v in contrasts.items()},
              'usage_per_turn': usage,
              'latency_seconds': {'n': sum(type(r.get('duration_seconds')) in (int, float) for r in chargeable),
                                  'mean': mean([r['duration_seconds'] for r in chargeable if type(r.get('duration_seconds')) in (int, float)]) if any(type(r.get('duration_seconds')) in (int, float) for r in chargeable) else None},
              'quality_checks': {'grade_format_valid': sum(v is not None for v in scored.values()),
                                 'grade_records': len(scored),
                                 'analysis_records': sum(r['stage'] == 'analyze' for r in actual.values()),
                                 'checks_as_recorded': [{'job_id': r['job_id'], 'checks': r.get('checks', r.get('validation', {}))} for r in actual.values()],
                                 'semantic_analysis_review': 'Unverified unless explicitly recorded; all original analysis is preserved below.'}, 'blocked_records_excluded_from_usage': len(actual)-len(chargeable),
              'sessions': {'observed_thread_count': len(threads), 'observed_threads': dict(threads),
                           'planned_logical_sessions': len(logical), 'planned_logical_turn_shapes': dict(Counter(logical.values())),
                           'native_verification': 'Separate runner verification required; counts do not establish native history semantics.'},
              'records': records}
    out = run / 'report'
    out.mkdir(exist_ok=True)
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    caveats = ('점수는 논증 품질: 주장 명확성·근거 연결·한계 고려 각 0–4, 합계 0–12점이다. 사용자 100/70점과 다르다.\n'
               'I는 판정 1단계, S2/M2는 분석→판정 2단계이므로 기준선 차이를 순수 이력 효과로 해석하지 않는다.\n'
               '1,090호출은 독립 표본이 아니다. p값·동등성·정확도/공정성 향상을 선언하지 않는다. 결측·실패는 0점으로 대체하지 않는다.\n')
    overview = '# 실제 관측 보고\n\n'+caveats+'\n| 조건 | 현재 글 유효 n / 평균 | 중립 유효 n / 평균 |\n|---|---|---|\n'
    for cell, entry in cells.items():
        a, b = entry['current_grades'], entry['neutral_probe']
        overview += f"| {cell} {entry['label']} | {a['n']} / {a['means'].get('total')} | {b['n']} / {b['means'].get('total')} |\n"
    overview += '\n주 지표는 반복별 G_S=S2관대−엄격, G_M=M2관대−엄격, D=G_S−G_M이다.\n\n'
    overview += '```json\n'+json.dumps(result['primary'], ensure_ascii=False, indent=2)+'\n```\n'
    (out/'overview.md').write_text(overview, encoding='utf-8')
    observations = '# 전체 분석·판정 관측\n\n'+caveats
    for record in records:
        observations += '\n## '+record['job_id']+'\n\n```json\n'+json.dumps(record, ensure_ascii=False, indent=2)+'\n```\n'
    (out/'actual-observations.md').write_text(observations, encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    report(args.run)
