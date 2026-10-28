"""Offline native-session scheduling and failure-isolation tests; zero live calls."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
# Contracts are separately tested; these tests isolate the orchestration boundary.
if not (ROOT / 'src/contracts.py').exists():
    sys.modules.setdefault('contracts', types.ModuleType('contracts'))
import run_experiment as runner


class FakeContracts:
    @staticmethod
    def instructions():
        return 'Shared evaluation instructions'

    @staticmethod
    def payload(job, text, analysis):
        result = {'mode': 'analyze' if job['stage'] == 'analyze' else 'judge', 'current_submission': {k: text[k] for k in ['submission_id', 'author_id', 'text']}}
        if job['stage'] != 'analyze' and job['arm'] != 'I':
            result['current_analysis'] = analysis
        return result

    @staticmethod
    def schema(stage):
        return {'type': 'object', 'stage': stage}

    @staticmethod
    def validate_response(stage, response, text):
        if response.get('bad'):
            raise ValueError('invalid response')

    @staticmethod
    def analysis_flags(response, text):
        return []


class FakeFactory:
    def __init__(self, fail=None):
        self.adapters = []
        self.active = 0
        self.maximum = 0
        self.fail = fail

    def __call__(self):
        owner = self
        class Adapter:
            def __init__(self):
                self.prompts = []
                self.closed = 0
                self.session = None
                self.thread = 'fake-thread-' + str(len(owner.adapters))
                owner.adapters.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                self.closed += 1

            async def start_session(self, instructions, role, trace):
                self.role, self.trace = role, trace
                self.session = self
                return self

            async def step(self, prompt, output_schema, timeout):
                assert timeout == 90
                self.prompts.append(json.loads(prompt))
                owner.active += 1
                owner.maximum = max(owner.maximum, owner.active)
                await asyncio.sleep(0)
                owner.active -= 1
                response = {'mode': self.prompts[-1]['mode'], 'marker': self.thread}
                if owner.fail and owner.fail(self, self.prompts[-1]):
                    response = {'bad': True}
                return {'text': json.dumps(response), 'usage': {'input_tokens': 5, 'output_tokens': 2},
                        'status': 'completed', 'thread_id': self.thread,
                        'turn_id': f'{self.thread}-turn-{len(self.prompts)}',
                        'selected_model': 'gpt-6-luna', 'duration_seconds': .01}
        return Adapter()


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def execute_fake(self, tmp, factory):
        with patch.object(runner, 'contracts', FakeContracts):
            instance = runner.Runner(ROOT, Path(tmp), factory)
            records = await instance.run(require_preflight=False)
        return instance, records

    async def test_full_native_topology_payloads_and_global_limit(self):
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as tmp:
            instance, records = await self.execute_fake(tmp, factory)
            self.assertEqual(len(records), 1090)
            progress = json.loads((Path(tmp) / 'progress.json').read_text())
            self.assertEqual((progress['planned_calls'], progress['completed'], progress['completed_sessions']), (1090, 1090, 470))
            self.assertEqual((progress['failed'], progress['blocked']), (0, 0))
            self.assertTrue(all(r['status'] == 'completed' for r in records.values()))
            self.assertEqual(len(factory.adapters), 470)
            expected_blocks = list(dict.fromkeys(instance.jobs[j]['replicate'] for j in instance.plan['launch_priority']))
            self.assertEqual(list(dict.fromkeys(r['replicate'] for r in records.values())), expected_blocks)
            self.assertTrue(all(r['selected_model'] == 'gpt-6-luna' and r['sdk_raw_result']['thread_id'] == r['thread_id'] for r in records.values()))
            self.assertEqual(sorted(len(a.prompts) for a in factory.adapters).count(22), 20)
            self.assertEqual(sorted(len(a.prompts) for a in factory.adapters).count(11), 20)
            self.assertLessEqual(factory.maximum, 6)
            self.assertGreater(factory.maximum, 1)
            self.assertTrue(all(a.closed == 1 for a in factory.adapters))
            for adapter in factory.adapters:
                self.assertEqual(adapter.role, 'evaluation')
                for payload in adapter.prompts:
                    self.assertTrue(set(payload) <= {'mode', 'current_submission', 'current_analysis'})
                if len(adapter.prompts) == 11:
                    self.assertTrue(all(p['mode'] == 'analyze' and 'current_analysis' not in p for p in adapter.prompts))
                if len(adapter.prompts) == 22:
                    self.assertEqual([p['mode'] for p in adapter.prompts], ['analyze', 'judge'] * 11)
                    self.assertTrue(all(p['current_analysis']['marker'] == adapter.thread for p in adapter.prompts if p['mode'] == 'judge'))
            self.assertEqual(len(list((Path(tmp) / 'claims').glob('*.json'))), 1090)
            self.assertEqual(len(list((Path(tmp) / 'requests').glob('*.json'))), 1090)
            # Whole completed sessions are reusable without creating fresh threads.
            factory2 = FakeFactory()
            _, restored = await self.execute_fake(tmp, factory2)
            self.assertEqual(len(restored), 1090)
            self.assertEqual(factory2.adapters, [])

    async def test_s2_schema_failure_blocks_native_descendants(self):
        seen = set()
        def fail(adapter, payload):
            if len(adapter.prompts) == 2 and adapter.thread not in seen:
                seen.add(adapter.thread)
                return True
            return False
        with tempfile.TemporaryDirectory() as tmp:
            instance, records = await self.execute_fake(tmp, FakeFactory(fail))
            for blueprint in instance.blueprints:
                if blueprint['arm'] == 'S2':
                    states = [records[j]['status'] for j in blueprint['ordered_jobs']]
                    self.assertEqual(states, ['completed', 'failed'] + ['blocked'] * 20)

    async def test_m2_judge_failure_does_not_taint_analyst(self):
        # All fresh judges fail; S2 judge failures have their own session boundary.
        def fail(adapter, payload):
            return len(adapter.prompts) == 1 and payload['mode'] == 'judge' and 'current_analysis' in payload
        with tempfile.TemporaryDirectory() as tmp:
            instance, records = await self.execute_fake(tmp, FakeFactory(fail))
            analysts = [r for r in records.values() if r['arm'] == 'M2' and r['stage'] == 'analyze']
            self.assertEqual(len(analysts), 220)
            self.assertTrue(all(r['status'] == 'completed' for r in analysts))
            judges = [r for r in records.values() if r['arm'] == 'M2' and r['stage'] == 'judge']
            self.assertTrue(all(r['status'] == 'failed' for r in judges))

    async def test_partial_native_session_claim_rejects_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance = runner.Runner(ROOT, Path(tmp), FakeFactory())
            b = next(b for b in instance.blueprints if b['turn_count'] == 22)
            runner.exclusive(Path(tmp) / 'claims' / (b['ordered_jobs'][0] + '.json'), {'job_id': b['ordered_jobs'][0]})
            with self.assertRaisesRegex(RuntimeError, 'cannot be resumed'):
                instance.restore()

    async def test_manifest_guard_precedes_any_request_or_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'run-manifest.json').write_text('{}')
            factory = FakeFactory()
            instance = runner.Runner(ROOT, directory, factory)
            called = []
            def reject(root, run_dir):
                called.append((root, run_dir))
                raise ValueError('frozen source changed')
            with patch.dict(sys.modules, {'freeze': types.SimpleNamespace(guard=reject)}):
                with self.assertRaisesRegex(ValueError, 'frozen source changed'):
                    await instance.execute(next(j for j in instance.jobs.values() if not j['requires']))
            self.assertEqual(len(called), 1)
            self.assertEqual(factory.adapters, [])
            self.assertFalse((directory / 'requests').exists())

    def test_wire_preserves_payload_order_and_does_not_pretty_print(self):
        value = {'mode': 'judge', 'current_analysis': {'evidence': []}, 'current_submission': {'text': '한글'}}
        prompt = runner.wire(value)
        self.assertEqual(prompt, '{"mode":"judge","current_analysis":{"evidence":[]},"current_submission":{"text":"한글"}}')

    def test_event_guard_checks_metadata_only(self):
        runner.verify_events([{'type': 'item.completed', 'item_type': 'agent_message',
                               'text': '"tool_call" "compaction" are merely quoted source words'}])
        for event in [{'type': 'context_compacted'}, {'type': 'item.started', 'item_type': 'command_execution'},
                      {'type': 'item.completed', 'item_type': 'web_search'}]:
            with self.assertRaises(ValueError):
                runner.verify_events([event])

    def test_unauthorized_arm_or_count_rejected(self):
        plan = json.loads((ROOT / 'data/plan.json').read_text())
        blueprints = json.loads((ROOT / 'data/session-blueprints.json').read_text())
        bad = copy.deepcopy(plan)
        bad['jobs'][0]['arm'] = 'R'
        with self.assertRaises(ValueError):
            runner.validate_plan(bad, blueprints)
        bad = copy.deepcopy(plan)
        bad['jobs'].append(bad['jobs'][0])
        with self.assertRaises(ValueError):
            runner.validate_plan(bad, blueprints)


if __name__ == '__main__':
    unittest.main()
