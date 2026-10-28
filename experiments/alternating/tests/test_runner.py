"""Full offline native topology and host handoff tests; no provider calls."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
if not (ROOT / 'src/contracts.py').exists():
    sys.modules.setdefault('contracts', types.ModuleType('contracts'))
import boundary
import run_experiment as runner


class FakeContracts:
    @staticmethod
    def instructions(role):
        return 'Fixed ' + role + ' instructions'

    @staticmethod
    def make_payload(job, submission, records):
        if job['stage'] == 'route':
            return boundary.route_input(job['request_id'], submission)
        if job['stage'] == 'deliver':
            return boundary.result_input(job['request_id'], job['evaluation_id'], records[job['evaluation_job_id']]['response'])
        if job.get('route_job_id'):
            return boundary.delegate(records[job['route_job_id']]['response'], job['request_id'], submission)
        return boundary.evaluation_payload(submission)

    @staticmethod
    def schema(stage):
        return {'type': 'object', 'stage': stage}

    @staticmethod
    def validate_response(job, response, submission, records):
        if job['stage'] == 'route':
            boundary.delegate(response, job['request_id'], submission)
        elif job['stage'] == 'deliver':
            boundary.deliver(response, job['request_id'], job['evaluation_id'], records[job['evaluation_job_id']]['response'])
        elif set(response) != {'analysis', 'scores', 'reason'}:
            raise ValueError('invalid evaluation')

    @staticmethod
    def flags(response, submission):
        return []


class FakeFactory:
    def __init__(self, fail=None, raw_change=None):
        self.adapters = []
        self.active = self.maximum = 0
        self.fail, self.raw_change = fail, raw_change

    def __call__(self):
        owner = self
        class Adapter:
            def __init__(self):
                self.prompts = []
                self.closed = 0
                self.thread = 'fake-thread-' + str(len(owner.adapters))
                owner.adapters.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                self.closed += 1

            async def start_session(self, instructions, role, trace):
                self.instructions, self.role, self.trace = instructions, role, trace
                return self

            async def step(self, prompt, output_schema, timeout):
                assert timeout == 90
                payload = json.loads(prompt)
                self.prompts.append(payload)
                owner.active += 1
                owner.maximum = max(owner.maximum, owner.active)
                await asyncio.sleep(0)
                owner.active -= 1
                if payload.get('event') == 'user_evaluation_request':
                    response = {'action': 'delegate', 'request_id': payload['request_id']}
                elif payload.get('event') == 'evaluation_completed':
                    response = {'action': 'deliver', 'request_id': payload['request_id'], 'evaluation_id': payload['evaluation_id']}
                else:
                    response = {'analysis': {'marker': self.thread}, 'scores': [3, 3, 3], 'reason': '현재 원문 근거'}
                if owner.fail and owner.fail(self, payload):
                    response['bad'] = True
                # Whitespace intentionally differs from host JSON serialization.
                raw = {'text': json.dumps(response, ensure_ascii=False, indent=3) + '\n',
                       'usage': {'input_tokens': 5, 'output_tokens': 2}, 'status': 'completed',
                       'thread_id': self.thread, 'turn_id': f'{self.thread}-turn-{len(self.prompts)}',
                       'selected_model': 'gpt-6-luna', 'duration_seconds': .01}
                if owner.raw_change:
                    owner.raw_change(self, raw)
                return raw
        return Adapter()


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def execute_fake(self, tmp, factory):
        with patch.object(runner, 'contracts', FakeContracts):
            instance = runner.Runner(ROOT, Path(tmp), factory)
            records = await instance.run(require_preflight=False)
        return instance, records

    async def test_full_native_topology_wire_handoff_and_global_limit(self):
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as tmp:
            instance, records = await self.execute_fake(tmp, factory)
            directory = Path(tmp)
            self.assertEqual(len(records), 1090)
            self.assertTrue(all(r['status'] == 'completed' for r in records.values()))
            progress = json.loads((directory / 'progress.json').read_text())
            self.assertEqual((progress['completed'], progress['completed_sessions']), (1090, 470))
            self.assertEqual(len(factory.adapters), 470)
            self.assertEqual(sum(len(a.prompts) == 22 for a in factory.adapters), 20)
            self.assertEqual(sum(len(a.prompts) == 11 for a in factory.adapters), 20)
            self.assertEqual(sum(len(a.prompts) == 1 for a in factory.adapters), 430)
            self.assertLessEqual(factory.maximum, 6)
            self.assertGreater(factory.maximum, 1)
            self.assertTrue(all(a.closed == 1 for a in factory.adapters))
            expected_blocks = list(dict.fromkeys(instance.jobs[j]['replicate'] for j in instance.plan['launch_priority']))
            self.assertEqual(list(dict.fromkeys(r['replicate'] for r in records.values())), expected_blocks)
            evaluator_requests = {}
            for record in records.values():
                request_path = directory / 'requests' / (record['job_id'] + '.json')
                request = json.loads(request_path.read_text())
                self.assertEqual(json.loads(request['prompt']), request['payload'])
                self.assertEqual(record['request_sha256'], runner.digest(request_path.read_bytes()))
                self.assertEqual(request['instructions'], FakeContracts.instructions(record['role']))
                if record['stage'] == 'evaluate':
                    self.assertEqual(set(request['payload']), {'current_submission'})
                    evaluator_requests.setdefault(record['submission_id'], set()).add((request['prompt'], request['instructions'], runner.wire(request['schema'])))
                if record['stage'] == 'deliver':
                    source = records[record['evaluation_job_id']]
                    self.assertEqual(request['payload']['evaluation'], source['response'])
                    self.assertEqual(Path(record['delivery_path']).read_bytes(), source['response_text'].encode())
                    self.assertEqual(record['delivery_source_sha256'], record['delivery_sha256'])
                    evidence = json.loads((directory / 'delivery-evidence' / (record['job_id'] + '.json')).read_text())
                    self.assertEqual(evidence['source_sha256'], source['response_sha256'])
                    self.assertEqual(evidence['original_request_sha256'], records[record['route_job_id']]['request_sha256'])
            self.assertTrue(all(len(variants) == 1 for variants in evaluator_requests.values()))
            for adapter in factory.adapters:
                self.assertEqual(adapter.instructions, FakeContracts.instructions(adapter.role))
                if adapter.role == 'coordinator':
                    self.assertEqual([p['event'] for p in adapter.prompts], ['user_evaluation_request', 'evaluation_completed'] * 11)
                else:
                    self.assertTrue(all(set(p) == {'current_submission'} for p in adapter.prompts))
            self.assertEqual(len(list((directory / 'claims').glob('*.json'))), 1090)
            self.assertEqual(len(list((directory / 'session-ledger').glob('*.json'))), 470)
            factory2 = FakeFactory()
            _, restored = await self.execute_fake(tmp, factory2)
            self.assertEqual(len(restored), 1090)
            self.assertEqual(factory2.adapters, [])

    async def test_s_failure_blocks_native_descendants_without_retry(self):
        factory = FakeFactory(lambda adapter, payload: adapter.role == 'evaluator' and len(adapter.prompts) == 2)
        with tempfile.TemporaryDirectory() as tmp:
            instance, records = await self.execute_fake(tmp, factory)
            for blueprint in instance.blueprints:
                if blueprint['arm'] == 'S':
                    self.assertEqual([records[j]['status'] for j in blueprint['ordered_jobs']], ['completed', 'failed'] + ['blocked'] * 9)
            self.assertTrue(all(a.closed == 1 for a in factory.adapters))

    async def test_b_failure_blocks_coordinator_and_later_b(self):
        # Isolated evaluators fail, including I. Persistent S remains valid.
        factory = FakeFactory(lambda adapter, payload: adapter.role == 'evaluator' and len(adapter.prompts) == 1)
        with tempfile.TemporaryDirectory() as tmp:
            instance, records = await self.execute_fake(tmp, factory)
            for blueprint in instance.blueprints:
                if blueprint['role'] == 'coordinator':
                    self.assertEqual([records[j]['status'] for j in blueprint['ordered_jobs']], ['completed'] + ['blocked'] * 21)
            self.assertEqual(sum(r['status'] == 'failed' and r['arm'] == 'M' for r in records.values()), 20)
            self.assertTrue(all(a.closed == 1 for a in factory.adapters))
            self.assertFalse((Path(tmp) / 'deliveries').exists())

    async def test_route_extra_information_blocks_b(self):
        factory = FakeFactory(lambda adapter, payload: payload.get('event') == 'user_evaluation_request')
        with tempfile.TemporaryDirectory() as tmp:
            instance, records = await self.execute_fake(tmp, factory)
            self.assertTrue(all(r['status'] == 'blocked' for r in records.values() if r['arm'] == 'M' and r['stage'] == 'evaluate'))
            self.assertFalse((Path(tmp) / 'deliveries').exists())

    async def test_partial_native_session_claim_rejects_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance = runner.Runner(ROOT, Path(tmp), FakeFactory())
            blueprint = next(b for b in instance.blueprints if b['turns'] == 22)
            jid = blueprint['ordered_jobs'][0]
            runner.exclusive(Path(tmp) / 'claims' / (jid + '.json'), {'job_id': jid})
            with self.assertRaisesRegex(RuntimeError, 'cannot be resumed'):
                instance.restore()

    async def test_manifest_guard_precedes_request_or_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'run-manifest.json').write_text('{}')
            factory = FakeFactory()
            instance = runner.Runner(ROOT, directory, factory)
            def reject(*_):
                raise ValueError('frozen source changed')
            with patch.dict(sys.modules, {'freeze': types.SimpleNamespace(guard=reject)}):
                with self.assertRaisesRegex(ValueError, 'frozen source changed'):
                    await instance.execute(next(j for j in instance.jobs.values() if not j['requires']))
            self.assertEqual(factory.adapters, [])
            self.assertFalse((directory / 'requests').exists())

    async def test_fatal_model_or_native_identity_mismatch(self):
        for mutation in [lambda adapter, raw: raw.update(selected_model='other-model'),
                         lambda adapter, raw: raw.update(thread_id=None),
                         lambda adapter, raw: raw.update(turn_id=None)]:
            with tempfile.TemporaryDirectory() as tmp:
                instance = runner.Runner(ROOT, Path(tmp), FakeFactory(raw_change=mutation))
                first = next(j for j in instance.jobs.values() if not j['requires'])
                with patch.object(runner, 'contracts', FakeContracts):
                    record = await instance.execute(first)
                self.assertEqual(record['status'], 'failed')
                self.assertIsNotNone(instance.fatal)
                self.assertEqual(len(list((Path(tmp) / 'claims').glob('*.json'))), 1)

    async def test_compaction_event_is_fatal_and_failed_delivery_is_not_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / 'events.jsonl'
            events_path.write_text(json.dumps({'type': 'context_compacted'}) + '\n')
            factory = FakeFactory(raw_change=lambda adapter, raw: raw.update(events_path=str(events_path)))
            instance = runner.Runner(ROOT, Path(tmp), factory)
            first = next(j for j in instance.jobs.values() if not j['requires'])
            with patch.object(runner, 'contracts', FakeContracts):
                record = await instance.execute(first)
            self.assertEqual(record['status'], 'failed')
            self.assertIn('compaction', instance.fatal)
        with tempfile.TemporaryDirectory() as tmp:
            factory = FakeFactory(lambda adapter, payload: payload.get('event') == 'evaluation_completed')
            instance = runner.Runner(ROOT, Path(tmp), factory)
            delivery = next(j for j in instance.jobs.values() if j['stage'] == 'deliver')
            route = instance.jobs[delivery['route_job_id']]
            evaluation = instance.jobs[delivery['evaluation_job_id']]
            with patch.object(runner, 'contracts', FakeContracts):
                for job in [route, evaluation, delivery]:
                    await instance.execute(job)
            self.assertEqual(instance.records[delivery['job_id']]['status'], 'failed')
            self.assertFalse((Path(tmp) / 'deliveries').exists())

    def test_event_guard_rejects_tools_and_compaction(self):
        runner.verify_events([{'type': 'item.completed', 'item_type': 'agent_message', 'text': 'compaction is source text'}])
        for event in [{'type': 'context_compacted'}, {'type': 'item.started', 'item_type': 'command_execution'}, {'type': 'item.completed', 'item_type': 'web_search'}]:
            with self.assertRaises(ValueError):
                runner.verify_events([event])

    def test_unauthorized_scope_and_topology_rejected(self):
        plan = json.loads((ROOT / 'data/plan.json').read_text())
        blueprints = json.loads((ROOT / 'data/plan-sessions.json').read_text())
        for mutate in [lambda p: p.update(scope='alternating'), lambda p: p['jobs'][0].update(arm='R'), lambda p: p['jobs'][0].update(role='coordinator')]:
            bad = copy.deepcopy(plan)
            mutate(bad)
            with self.assertRaises(ValueError):
                runner.validate_plan(bad, blueprints)


if __name__ == '__main__':
    unittest.main()
