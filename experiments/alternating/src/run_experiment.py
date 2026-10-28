"""Main-only persistent native-session scheduler. No replay or automatic retry."""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time
from datetime import datetime, timezone
import contracts


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'



def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=False)


def verify_events(events):
    allowed_types = {'thread.started', 'turn.started', 'turn.completed', 'turn.failed',
                     'item.started', 'item.updated', 'item.completed', 'error'}
    allowed_items = {'agent_message', 'reasoning', 'error'}
    for event in events:
        if event.get('type') not in allowed_types or (event.get('item_type') is not None and event['item_type'] not in allowed_items):
            raise ValueError('Forbidden or unrecognized SDK event type/item_type')


def exclusive(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(encode(value))
        stream.flush()
        import os
        os.fsync(stream.fileno())


def validate_plan(plan, blueprints):
    jobs = plan['jobs']
    if plan.get('scope') != 'alternating_standalone' or len(jobs) != 1090:
        raise ValueError('Only the authorized main 1090-call plan is accepted')
    if Counter(j['arm'] for j in jobs) != {'I': 210, 'S': 220, 'M': 660}:
        raise ValueError('Unauthorized arms or counts')
    if Counter(j['stage'] for j in jobs) != {'evaluate': 650, 'route': 220, 'deliver': 220}:
        raise ValueError('Stage counts differ')
    if any(j['replicate'] not in range(1, 11) or j['role'] != ('coordinator' if j['stage'] in {'route', 'deliver'} else 'evaluator') for j in jobs):
        raise ValueError('Unauthorized role or replicate')
    by_id = {j['job_id']: j for j in jobs}
    if len(by_id) != 1090 or len(blueprints) != 470 or set(plan['launch_priority']) != set(by_id) or len(plan['launch_priority']) != 1090:
        raise ValueError('Invalid job/session inventory')
    seen = []
    keys = set()
    for blueprint in blueprints:
        key = blueprint['session_key']
        if key in keys:
            raise ValueError('Duplicate session key')
        keys.add(key)
        ordered = [by_id[i] for i in blueprint['ordered_jobs']]
        if len(ordered) != blueprint['turns']:
            raise ValueError('Blueprint count differs')
        if [j['session_turn'] for j in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError('Noncontiguous session turns')
        if any(j['session_key'] != key or j['arm'] != blueprint['arm'] or j['role'] != blueprint['role'] or j['replicate'] != blueprint['replicate'] for j in ordered):
            raise ValueError('Blueprint binding differs')
        expected = 22 if blueprint['role'] == 'coordinator' else (11 if blueprint['arm'] == 'S' else 1)
        if len(ordered) != expected:
            raise ValueError('Invalid persistent role topology')
        stages = [j['stage'] for j in ordered]
        if stages != (['route', 'deliver'] * 11 if blueprint['role'] == 'coordinator' else ['evaluate'] * expected):
            raise ValueError('Invalid native role stages')
        for index, job in enumerate(ordered):
            if any(dep not in by_id for dep in job['requires']):
                raise ValueError('Unknown dependency')
            if index and ordered[index-1]['job_id'] not in job['requires']:
                raise ValueError('Missing native-session predecessor')
        seen.extend(blueprint['ordered_jobs'])
    if Counter(seen) != Counter(by_id.keys()):
        raise ValueError('Blueprint coverage differs')
    for job in jobs:
        if job['arm'] != 'M':
            if job['role'] != 'evaluator' or job['stage'] != 'evaluate':
                raise ValueError('Only M may coordinate')
            continue
        if job['stage'] == 'evaluate':
            route = by_id.get(job.get('route_job_id'), {})
            if route.get('stage') != 'route' or job['requires'] != [route.get('job_id')]:
                raise ValueError('Invalid evaluator delegation dependency')
            if any(job.get(field) != route.get(field) for field in ('request_id', 'submission_id', 'replicate', 'position')):
                raise ValueError('Delegation identity differs')
        elif job['stage'] == 'deliver':
            evaluation = by_id.get(job.get('evaluation_job_id'), {})
            route = by_id.get(job.get('route_job_id'), {})
            if evaluation.get('stage') != 'evaluate' or route.get('stage') != 'route':
                raise ValueError('Invalid delivery sources')
            if set(job['requires']) != {route.get('job_id'), evaluation.get('job_id')}:
                raise ValueError('Invalid delivery dependencies')
            if any(job.get(field) != evaluation.get(field) for field in ('request_id', 'evaluation_id', 'submission_id', 'route_job_id')) or job['session_key'] != route.get('session_key'):
                raise ValueError('Delivery identity differs')
    for b in blueprints:
        if b['arm']=='I':continue
        ordered=[by_id[j] for j in b['ordered_jobs']]
        first='warm' if b['sequence']=='warm_first' else 'cool'
        assert b['sequence'] in ('warm_first','cool_first')
        for j in ordered:
            assert j['pattern']=='alternating'
            expected='neutral' if j['position']==11 else (first if j['position']%2 else ('cool' if first=='warm' else 'warm'))
            assert j['input_tone']==expected,'Nonalternating assignment'
    return by_id


def read_preflight(root, run_dir):
    proof = json.loads((run_dir / 'preflight.json').read_text())
    if proof.get('status') != 'passed':
        raise ValueError('Passing preflight is required')
    for label, path in [('contracts', root / 'src/contracts.py'), ('boundary', root / 'src/boundary.py'), ('adapter', root.parent.parent / 'backend/src/sdk_adapter.py')]:
        if proof.get(label + '_sha256') != digest(path.read_bytes()):
            raise ValueError(label + ' changed after preflight')
    for label, filename in [('bridge', 'sdk_bridge.mjs'), ('wrapper', 'sdk_exec_wrapper.py')]:
        path = root.parent.parent / 'backend/src' / filename
        if not path.exists() or proof.get(label + '_sha256') != digest(path.read_bytes()):
            raise ValueError(label + ' changed after preflight')
    return proof


class Runner:
    def __init__(self, root, run_dir, adapter_factory=None):
        self.root, self.run_dir = Path(root), Path(run_dir)
        self.plan = json.loads((self.root / 'data/plan.json').read_text())
        self.blueprints = json.loads((self.root / 'data/plan-sessions.json').read_text())
        self.jobs = validate_plan(self.plan, self.blueprints)
        self.blueprint = {b['session_key']: b for b in self.blueprints}
        submissions = json.loads((self.root / 'data/stimuli.json').read_text())
        submissions.append(json.loads((self.root / 'data/neutral-probe.json').read_text()))
        self.submissions = {s['submission_id']: s for s in submissions}
        self.adapter_factory = adapter_factory
        self.records = {}
        self.thread_bindings = {}
        self.turn_ids = set()
        self.sessions = {}
        self.locks = defaultdict(asyncio.Lock)
        self.tainted = set()
        self.slots = asyncio.Semaphore(6)
        self.fatal = None
        self.closed = {}

    def restore(self):
        records = {p.stem: json.loads(p.read_text()) for p in (self.run_dir / 'records').glob('*.json')}
        claims = {p.stem for p in (self.run_dir / 'claims').glob('*.json')}
        if set(records) - set(self.jobs) or claims - set(self.jobs):
            raise ValueError('Foreign records or claims')
        for b in self.blueprints:
            present = set(b['ordered_jobs']) & (set(records) | claims)
            if present and (present != set(b['ordered_jobs']) or any(records.get(j, {}).get('status') != 'completed' for j in b['ordered_jobs'])):
                raise RuntimeError('Incomplete native session cannot be resumed with a fresh session: ' + b['session_key'])
        self.records = records
        restored_bindings = {}
        for record in records.values():
            thread = record.get('thread_id')
            key = record['session_key']
            if not thread or (thread in self.thread_bindings and self.thread_bindings[thread] != key):
                raise RuntimeError('Imported thread binding invalid')
            if key in restored_bindings and restored_bindings[key] != thread:
                raise RuntimeError('Imported logical session changed thread')
            turn = record.get('turn_id')
            if not turn or (thread, turn) in self.turn_ids:
                raise RuntimeError('Imported native turn identity invalid')
            self.turn_ids.add((thread, turn))
            restored_bindings[key] = thread
            self.thread_bindings[thread] = key

    async def session(self, key):
        if key not in self.sessions:
            factory = self.adapter_factory or contracts.load_adapter()
            adapter = factory()
            trace = self.run_dir / 'traces' / key
            async def initialize():
                await adapter.__aenter__()
                return await adapter.start_session(contracts.instructions(self.blueprint[key]['role']), self.blueprint[key]['role'], trace)
            try:
                session = await asyncio.wait_for(initialize(), 30)
            except BaseException:
                await adapter.__aexit__(None, None, None)
                raise
            self.sessions[key] = (adapter, session, trace, None)
        return self.sessions[key]

    async def execute(self, job):
        key, jid = job['session_key'], job['job_id']
        async with self.locks[key]:
            if (self.run_dir / 'run-manifest.json').exists():
                from freeze import guard
                guard(self.root, self.run_dir)
            created = now()
            record = dict(job, status='blocked', response=None, usage=None, duration_seconds=0,
                          thread_id=None, turn_id=None, created_at=created, finished_at=None, error=None)
            if self.fatal or key in self.tainted or any(self.records[d]['status'] != 'completed' for d in job['requires']):
                record['error'] = self.fatal or 'dependency_or_native_session_failed'
                self.tainted.add(key)
                if key in self.sessions:
                    adapter, _, _, thread = self.sessions.pop(key)
                    await adapter.__aexit__(None, None, None)
                    self.closed[key] = thread
            else:
                submission = self.submissions[job['submission_id']]
                prompt = wire(contracts.make_payload(job, submission, self.records))
                output_schema = contracts.schema(job['stage'])
                request = {'payload': json.loads(prompt), 'job_id': jid, 'session_key': key, 'session_turn': job['session_turn'],
                           'role': job['role'], 'stage': job['stage'],
                           'instructions_profile': job['role'],
                           'prompt': prompt, 'instructions': contracts.instructions(job['role']), 'schema': output_schema,
                           'created_at': created, 'prompt_sha256': digest(prompt.encode()),
                           'instructions_sha256': digest(contracts.instructions(job['role']).encode()),
                           'schema_sha256': digest(encode(output_schema).encode())}
                request_path = self.run_dir / 'requests' / (jid + '.json')
                exclusive(request_path, request)
                record.update(request_path=str(request_path.resolve()), request_sha256=digest(request_path.read_bytes()),
                              prompt_sha256=request['prompt_sha256'],
                              original_submission_sha256=digest(wire({k: submission[k] for k in ('submission_id', 'author_id', 'text')}).encode()))
                exclusive(self.run_dir / 'claims' / (jid + '.json'), {'job_id': jid, 'created_at': created, 'request_sha256': record['request_sha256']})
                began = time.monotonic()
                raw = {}
                try:
                    async with self.slots:
                        adapter, session, trace, bound = await self.session(key)
                        record['started_at'] = now()
                        raw = await session.step(prompt, output_schema, 90)
                    record.update(sdk_step=job['session_turn'], usage_semantics='per_step_difference_of_observed_thread_total', usage=raw.get('usage'), duration_seconds=raw.get('duration_seconds', time.monotonic()-began),
                                  thread_id=raw.get('thread_id'), turn_id=raw.get('turn_id'), selected_model=raw.get('selected_model'),
                                  model_id=raw.get('selected_model'), sdk_raw_result=raw,
                                  sdk_events_path=raw.get('events_path'), sdk_metadata_path=str((trace / f"step-{job['session_turn']:03d}.metadata.json").resolve()),
                                  sdk_result_path=str((trace / f"step-{job['session_turn']:03d}.result.json").resolve()))
                    thread = raw.get('thread_id')
                    if not thread or not raw.get('turn_id') or (thread, raw.get('turn_id')) in self.turn_ids or (bound and bound != thread) or (thread in self.thread_bindings and self.thread_bindings[thread] != key):
                        self.fatal = 'Native thread/turn identity invariant failed'
                        raise RuntimeError(self.fatal)
                    self.thread_bindings[thread] = key
                    self.turn_ids.add((thread, raw['turn_id']))
                    self.sessions[key] = adapter, session, trace, thread
                    if raw.get('status') != 'completed' or raw.get('selected_model') != 'gpt-6-luna':
                        self.fatal = 'SDK status/model mismatch'
                        raise RuntimeError(self.fatal)
                    events_path = raw.get('events_path')
                    if events_path and Path(events_path).exists():
                        events = [json.loads(line) for line in Path(events_path).read_text().splitlines() if line.strip()]
                        try:
                            verify_events(events)
                        except ValueError:
                            self.fatal = 'Forbidden tool, context compaction, or unrecognized SDK event'
                            raise
                    response = json.loads(raw['text'])
                    contracts.validate_response(job, response, submission, self.records)
                    record.update(status='completed', response=response, response_text=raw['text'],
                                  response_sha256=digest(raw['text'].encode()))
                    if job.get('route_job_id'):
                        record['original_request_sha256'] = self.records[job['route_job_id']]['request_sha256']
                        record['original_request_hash_semantics'] = 'route_request_envelope_file_bytes'
                    if job['stage'] == 'evaluate':
                        record['evaluation_payload_sha256'] = request['prompt_sha256']
                    if job['stage'] == 'deliver':
                        source = self.records[job['evaluation_job_id']]
                        original = source['response_text'].encode()
                        delivery_path = self.run_dir / 'deliveries' / (jid + '.json')
                        delivery_path.parent.mkdir(parents=True, exist_ok=True)
                        with delivery_path.open('xb') as stream:
                            stream.write(original)
                            stream.flush()
                            import os
                            os.fsync(stream.fileno())
                        record['delivery_source_sha256'] = source['response_sha256']
                        record['delivery_sha256'] = digest(delivery_path.read_bytes())
                        record['delivered_sha256'] = record['delivery_sha256']
                        record['delivery_path'] = str(delivery_path.resolve())
                        exclusive(self.run_dir / 'delivery-evidence' / (jid + '.json'), {
                            'job_id': jid, 'request_id': job['request_id'], 'evaluation_id': job['evaluation_id'],
                            'evaluation_job_id': job['evaluation_job_id'],
                            'source_sha256': source['response_sha256'],
                            'delivered_sha256': record['delivery_sha256'],
                            'coordinator_host_event_request_sha256': record['request_sha256'],
                            'original_request_sha256': record['original_request_sha256'],
                            'delivery_path': record['delivery_path']})
                    if job['stage'] == 'evaluate':
                        record['flags'] = contracts.flags(response, submission)
                except asyncio.CancelledError:
                    raise  # Claim and request deliberately survive host interruption.
                except Exception as exc:
                    if type(exc).__name__=='SDKIsolationError':
                        self.fatal='SDK isolation verification failed'
                    if 'counter decreased' in str(exc):
                        self.fatal = 'Cumulative token usage counter decreased'
                    if hasattr(exc, 'record'):
                        raw = exc.record
                        if raw.get('error_type') in {'builtin_tool_invocation', 'compaction', 'model_or_effort_mismatch', 'permissions_mismatch', 'cli_version_mismatch'}:
                            self.fatal = raw['error_type']
                        record.update(usage=raw.get('usage'), thread_id=raw.get('thread_id'), turn_id=raw.get('turn_id'), sdk_events_path=raw.get('events_path'), selected_model=raw.get('selected_model'), model_id=raw.get('selected_model'), sdk_raw_result=raw)
                    record.update(status='failed', error=f'{type(exc).__name__}: {exc}', raw_response=raw.get('text'), duration_seconds=time.monotonic()-began)
                    self.tainted.add(key)
                finally:
                    if key in self.sessions and (key in self.tainted or job['session_turn'] == self.blueprint[key]['turns']):
                        adapter, _, _, _ = self.sessions.pop(key)
                        await adapter.__aexit__(None, None, None)
                        self.closed[key] = record.get('thread_id')
            record['finished_at'] = now()
            exclusive(self.run_dir / 'records' / (jid + '.json'), record)
            self.records[jid] = record
            if key in self.closed:
                blueprint = self.blueprint[key]
                exclusive(self.run_dir / 'session-ledger' / (key + '.json'), {
                    'session_key': key, 'thread_id': self.closed.pop(key),
                    'ordered_jobs': blueprint['ordered_jobs'], 'closed_at': now(),
                    'status': 'completed' if all(self.records.get(j, {}).get('status') == 'completed' for j in blueprint['ordered_jobs']) else 'failed',
                    'trace_dir': str((self.run_dir / 'traces' / key).resolve())})
            self.write_progress()
            return record

    def write_progress(self):
        records = list(self.records.values())
        by_arm, by_stage = {}, {}
        for field, target in [('arm', by_arm), ('stage', by_stage)]:
            for label in sorted({r[field] for r in records}):
                target[label] = dict(Counter(r['status'] for r in records if r[field] == label))
        counts = Counter(r['status'] for r in records)
        completed_sessions = sum(all(self.records.get(j, {}).get('status') == 'completed' for j in b['ordered_jobs']) for b in self.blueprints)
        value = {'updated_at': now(), 'planned_calls': 1090, 'total': len(records),
                 'completed': counts['completed'], 'failed': counts['failed'], 'blocked': counts['blocked'],
                 'by_arm': by_arm, 'by_stage': by_stage, 'completed_sessions': completed_sessions,
                 'planned_sessions': 470, 'fatal': self.fatal}
        temporary = self.run_dir / 'progress.json.tmp'
        temporary.write_text(encode(value))
        temporary.replace(self.run_dir / 'progress.json')

    async def run(self, require_preflight=True):
        if require_preflight:
            read_preflight(self.root, self.run_dir)
        self.restore()
        active = {}
        try:
            replicates = list(dict.fromkeys(self.jobs[j]['replicate'] for j in self.plan['launch_priority']))
            for replicate in replicates:
                pending = [self.jobs[j] for j in self.plan['launch_priority'] if self.jobs[j]['replicate'] == replicate and j not in self.records]
                active = {}
                while pending or active:
                    for job in pending[:]:
                        if len(active) >= 6:
                            break
                        if all(d in self.records for d in job['requires']) and all(j['session_key'] != job['session_key'] for j in active.values()):
                            task = asyncio.create_task(self.execute(job))
                            active[task] = job
                            pending.remove(job)
                    if not active:
                        raise RuntimeError('Dependency deadlock')
                    done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        active.pop(task)
                        await task
        finally:
            for task in active:
                task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
            for adapter, _, _, _ in list(self.sessions.values()):
                await adapter.__aexit__(None, None, None)
            self.sessions.clear()
        return self.records


async def run(root, run_dir, adapter_factory=None, require_preflight=True):
    return await Runner(root, run_dir, adapter_factory).run(require_preflight)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    root, run_dir = args.root.resolve(), args.run_dir.resolve()
    if not run_dir.is_relative_to(root / 'runs') or run_dir == root / 'runs':
        parser.error('--run-dir must be a run directory under ROOT/runs')
    instance = Runner(root, run_dir)
    asyncio.run(instance.run())
    if instance.fatal:
        raise SystemExit('Fatal experiment invariant: ' + instance.fatal)


if __name__ == '__main__':
    main()
