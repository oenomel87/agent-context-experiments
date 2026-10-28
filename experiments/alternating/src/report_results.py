"""Offline, descriptive reporting for frozen v4 runs. No model calls."""
import argparse
import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

SCORE_KEYS = ('claim_clarity', 'support_linkage', 'qualification')


def distribution(values):
    values = list(values)
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'sd': statistics.stdev(values) if len(values) > 1 else None,
            'median': statistics.median(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None,
            'mean_absolute': statistics.mean(map(abs, values)) if values else None,
            'frequencies': dict(sorted(Counter(values).items()))}


def evaluation_total(record):
    if record.get('status') != 'completed':
        return None
    response = record.get('response', {})
    if not isinstance(response, dict):
        return None
    analysis, scores = response.get('analysis'), response.get('scores')
    if not isinstance(analysis, dict) or not all(k in analysis for k in ('claim', 'facts', 'evidence', 'limitations')):
        return None
    if not isinstance(scores, dict) or not isinstance(response.get('reason'), str):
        return None
    values = [scores.get(k) for k in SCORE_KEYS]
    if any(type(x) is not int or not 0 <= x <= 4 for x in values):
        return None
    return sum(values)


def build_report(run):
    run = Path(run)
    plan = json.loads((run / 'snapshots/data/plan.json').read_text())
    jobs = plan['jobs']
    records = {}
    for job in jobs:
        path = run / 'records' / (job['job_id'] + '.json')
        if path.exists():
            records[job['job_id']] = json.loads(path.read_text())
    totals = {j['job_id']: evaluation_total(records.get(j['job_id'], {}))
              for j in jobs if j['stage'] == 'evaluate' and j['role'] == 'evaluator'}
    groups = defaultdict(list)
    for j in jobs:
        groups[j['role']].append(j)
    operational = {}
    for role, group in groups.items():
        statuses = Counter(records.get(j['job_id'], {}).get('status', 'missing') for j in group)
        usage_keys = set()
        for j in group:
            usage_keys.update(k for k, v in (records.get(j['job_id'], {}).get('usage') or {}).items()
                              if isinstance(v, (int, float)) and not isinstance(v, bool))
        usage = {}
        for key in sorted(usage_keys):
            known = [(records.get(j['job_id'], {}).get('usage') or {}).get(key) for j in group]
            known = [v for v in known if isinstance(v, (int, float)) and not isinstance(v, bool)]
            usage[key] = {'known_records': len(known), 'unknown_records': len(group)-len(known), 'sum_known': sum(known)}
        operational[role] = {'planned': len(group), 'statuses': dict(statuses), 'usage': usage,
                             'duration_seconds': distribution(records[j['job_id']]['duration_seconds'] for j in group if j['job_id'] in records and records[j['job_id']].get('status') != 'blocked' and isinstance(records[j['job_id']].get('duration_seconds'), (int, float))),
                             'usage_records_known': sum(isinstance(records.get(j['job_id'], {}).get('usage'), dict) for j in group),
                             'usage_records_unknown': sum(not isinstance(records.get(j['job_id'], {}).get('usage'), dict) for j in group),
                             'usage_note': 'Missing usage is unknown; blocked jobs are not assumed attempted.'}
    def value(j):
        return totals.get(j['job_id'])
    cells = {}
    probe = {}
    direct = {}
    for arm in ('S', 'M'):
        for sequence in ('warm_first', 'cool_first'):
            selected = [j for j in jobs if j['arm'] == arm and j['stage'] == 'evaluate' and j['sequence'] == sequence]
            current = [j for j in selected if not j['is_probe'] and value(j) is not None]
            probes = [j for j in selected if j['is_probe'] and value(j) is not None]
            deltas = [(j, value(j)-totals[j['baseline_job_id']]) for j in current
                      if totals.get(j.get('baseline_job_id')) is not None]
            key = arm + '_' + sequence
            probe[key] = {j['replicate']: value(j) for j in probes}
            cells[key] = {'current_raw': distribution(value(j) for j in current),
                          'current_baseline_delta': distribution(d for _, d in deltas),
                          'position_baseline_delta': {str(p): distribution(d for j, d in deltas if j['position'] == p) for p in range(1, 11)},
                          'neutral_raw': distribution(value(j) for j in probes),
                          'neutral_baseline_delta': distribution(value(j)-totals[j['baseline_job_id']] for j in probes if totals.get(j.get('baseline_job_id')) is not None)}
    contrasts = {}
    per_arm = {}
    for arm in ('S', 'M'):
        warm, cool = probe[arm+'_warm_first'], probe[arm+'_cool_first']
        per_arm[arm] = {r: warm[r]-cool[r] for r in warm.keys() & cool.keys()}
        contrasts['G_'+arm] = {'per_replicate': per_arm[arm], 'distribution': distribution(per_arm[arm].values())}
    differences = {r: per_arm['S'][r]-per_arm['M'][r] for r in per_arm['S'].keys() & per_arm['M'].keys()}
    contrasts['D'] = {'definition': 'G_S - G_M', 'per_replicate': differences, 'distribution': distribution(differences.values())}
    lookup = {(j['arm'], j.get('sequence'), j['replicate'], j['submission_id']): value(j) for j in jobs if j['stage'] == 'evaluate' and j['arm'] in ('S', 'M') and value(j) is not None}
    for sequence in ('warm_first', 'cool_first'):
        pairs = []
        for j in jobs:
            if j['arm'] == 'S' and j['stage'] == 'evaluate' and j['sequence'] == sequence and value(j) is not None:
                other = lookup.get(('M', sequence, j['replicate'], j['submission_id']))
                if other is not None:
                    pairs.append({'replicate': j['replicate'], 'submission_id': j['submission_id'], 'is_probe': j['is_probe'], 'delta': value(j)-other})
        direct[sequence] = {'pairs': pairs, 'current': distribution(p['delta'] for p in pairs if not p['is_probe']), 'neutral': distribution(p['delta'] for p in pairs if p['is_probe'])}
    flags = {j['job_id']: {k: records[j['job_id']][k] for k in ('content_flags', 'analysis_flags', 'flags') if k in records[j['job_id']]}
             for j in jobs if j['job_id'] in records and any(k in records[j['job_id']] for k in ('content_flags', 'analysis_flags', 'flags'))}
    deliveries = [j for j in jobs if j['stage'] == 'deliver']
    delivery_checks = []
    for job in deliveries:
        record = records.get(job['job_id'], {})
        source = records.get(job['evaluation_job_id'], {})
        path = run / 'deliveries' / (job['job_id'] + '.json')
        if record.get('status') != 'completed':
            state = 'not_completed'
        elif not path.exists() or not isinstance(source.get('response_text'), str):
            state = 'unknown'
        else:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            expected = hashlib.sha256(source['response_text'].encode()).hexdigest()
            state = 'verified' if (actual == expected == record.get('delivery_sha256') == record.get('delivery_source_sha256') == source.get('response_sha256')) else 'mismatch'
        delivery_checks.append({'job_id': job['job_id'], 'state': state})
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'planned_calls': len(jobs),
              'valid_evaluations': sum(v is not None for v in totals.values()), 'operations_by_role': operational,
              'cells': cells, 'primary_neutral_contrasts': contrasts, 'direct_S_minus_M': direct,
              'baseline': {'valid_evaluations': sum(value(j) is not None for j in jobs if j['arm'] == 'I'), 'source': '210 immutable baseline records reused from experiments/homogeneous/observations.jsonl; no new baseline calls'},
              'delivery': {'planned': len(deliveries), 'coordinator_completed': sum(records.get(j['job_id'], {}).get('status') == 'completed' for j in deliveries), 'verified_user_delivered': sum(c['state'] == 'verified' for c in delivery_checks), 'checks': delivery_checks, 'states': dict(Counter(c['state'] for c in delivery_checks)), 'note': 'Coordinator completion alone does not establish user delivery. Delivery verification requires explicit host artifact evidence.'},
              'flags': flags,
              'interpretation': 'Scores measure argument quality on 0–12, not people or accuracy. B and I have identical current input by design; expected similarity is architectural. Shared cases and baselines preclude treating calls as independent samples. Descriptive only; no p-values. Valid evaluator outputs remain scientifically usable after relay failure, but do not establish end-to-end success.'}
    out = run / 'report'
    out.mkdir(parents=True, exist_ok=True)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    lines = ['# v4 offline report', '', f"Generated: {report['generated_at']}", f"Valid full evaluations: {report['valid_evaluations']} / {len(totals)}", '', report['interpretation'], '', '| Contrast | n | Mean | SD | Median | Mean absolute | Min | Max |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, c in contrasts.items():
        d = c['distribution']
        lines.append('| '+name+' | '+' | '.join(str(d[k]) for k in ('n','mean','sd','median','mean_absolute','min','max'))+' |')
    (out/'overview.md').write_text('\n'.join(lines)+'\n')
    (out/'actual-observations.md').write_text('# Actual observations\n\n'+f"Observed valid full evaluations: {report['valid_evaluations']}. Recorded files: {len(records)}.\n\n"+report['delivery']['note']+'\n\n'+report['interpretation']+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    report = build_report(args.run)
    print(f"Report written to {args.run / 'report'}; {report['valid_evaluations']} valid evaluations")


if __name__ == '__main__':
    main()
