"""Host-owned regression: no mocked test may claim real simulator or live Vultr evidence."""
import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import agent, config, mock as canned, sandbox, budget
from trusted import preflight, verdict
from trusted.lint_rtl import static_lint, validate_interface
from trusted.oracle import expected_counter_trace, load_counter_vectors

NONCE = '0123456789abcdef0123456789abcdef'


def trace():
    lines = [f'VLTB1|{NONCE}|BEGIN|counter|counter4_sync_v1']
    for row in expected_counter_trace(load_counter_vectors()):
        n = row['step']
        lines += [f'VLTB1|{NONCE}|IN|main|{n}|rst|1|{row["rst"]}',
                  f'VLTB1|{NONCE}|IN|main|{n}|en|1|{row["en"]}']
        if n:
            lines.append(f'VLTB1|{NONCE}|PRE|main|{n}|count|4|{row["pre"]:04b}')
        lines.append(f'VLTB1|{NONCE}|POST|main|{n}|count|4|{row["post"]:04b}')
    lines.append(f'VLTB1|{NONCE}|END|87|0')
    return '\n'.join(lines)


def sim(stdout=None, **kwargs):
    s = {'stage': 'sim', 'compile_rc': 0, 'rc': 0, 'stdout': trace() if stdout is None else stdout,
         'timeout': False}
    s.update(kwargs)
    return s


class PolicyTests(unittest.TestCase):
    def test_correct_ansi_interface(self):
        self.assertEqual(static_lint(canned.COUNTER_OK)[0], True)
        self.assertEqual(validate_interface(canned.COUNTER_OK, 'counter')[0], True)

    def test_forbidden_before_execution(self):
        attacks = [
            canned.COUNTER_OK.replace('endmodule', '$display("PASS"); endmodule'),
            canned.COUNTER_OK.replace('endmodule', '$display("VLTB1|fake|END|87|0"); endmodule'),
            canned.COUNTER_OK.replace('endmodule', '$display("@@RESULT@@{}"); endmodule'),
            canned.COUNTER_OK.replace('endmodule', 'initial begin $finish; end endmodule'),
            canned.COUNTER_OK.replace('endmodule', '`include "evil.v"\nendmodule'),
            canned.COUNTER_OK.replace('endmodule', '/* unterminated'),
            canned.COUNTER_OK.replace('endmodule', '/* nested /* inside */ endmodule'),
            canned.COUNTER_OK.replace('endmodule', 'always #1 count <= 0; endmodule'),
            canned.COUNTER_OK + ' ' * 20000,
            canned.COUNTER_OK.replace('input  wire       rst', 'input wire [1:0] rst'),
            canned.COUNTER_OK.replace('output reg  [3:0] count', 'output reg [4:0] count'),
            canned.COUNTER_OK.replace('output reg  [3:0] count', 'output reg [3:0] count, output wire extra'),
        ]
        for rtl in attacks:
            with self.subTest(rtl=rtl[-100:]):
                self.assertFalse(preflight.validate(rtl, 'counter')['ok'])

    def test_preflight_reject_never_calls_runner(self):
        job = {'id': 'unittest', 'request': 'counter', 'family': 'counter',
               'status': 'running', 'started': 0, 'events': [], 'attempts': []}
        rtl = canned.COUNTER_OK.replace('endmodule', '$display("PASS"); endmodule')
        with mock.patch.object(agent, 'MAX_ATTEMPTS', 1), \
             mock.patch.object(agent.llm, 'chat', return_value=(json.dumps({'rtl': rtl, 'notes': ''}), {'mock': True})), \
             mock.patch.object(agent.sandbox, 'run_sim') as run_sim, \
             mock.patch.object(agent, '_save_sample'):
            agent.run(job)
        run_sim.assert_not_called()
        self.assertEqual(job['attempts'][0]['result']['verdict']['reason'], 'RTL_POLICY_VIOLATION')
        self.assertEqual(job['status'], 'failed')

    def test_backend_image_stages_every_pinned_file(self):
        # Docker is unavailable in this test environment; ensure its build
        # recipe at least includes all files under the expected directories.
        df = (Path(__file__).resolve().parent.parent / 'Dockerfile').read_text()
        for statement in ('COPY app ./app', 'COPY trusted ./trusted',
                          'COPY sandbox ./sandbox', 'COPY Dockerfile ./Dockerfile',
                          'COPY docker-compose.yml ./docker-compose.yml',
                          'COPY deploy.sh ./deploy.sh'):
            self.assertIn(statement, df)


class VerdictTests(unittest.TestCase):
    def test_synthetic_protocol_fixture_only(self):
        # Not an actual DUT simulation and NOT evidence that RTL works.
        r = verdict.judge(canned.COUNTER_OK, 'counter', NONCE, sim())
        self.assertEqual(r['reason'], 'ORACLE_AGREEMENT')
        self.assertEqual(r['observations_checked'], 87)

    def test_protocol_mutations_never_pass(self):
        original = trace().splitlines()
        mutations = {
            'remove': '\n'.join(original[:-2] + original[-1:]),
            'duplicate': '\n'.join(original[:-1] + [original[5]] + original[-1:]),
            'reordered': '\n'.join(original[:3] + [original[4], original[3]] + original[5:]),
            'xz': trace().replace('|count|4|0000', '|count|4|00xz', 1),
            'incorrect_width': trace().replace('|count|4|0000', '|count|5|00000', 1),
            'incorrect_case': trace().replace('|IN|main|', '|IN|other|', 1),
            'wrong_nonce': trace().replace(NONCE, 'f' * 32, 1),
            'wrong_value': trace().replace('|POST|main|1|count|4|0001', '|POST|main|1|count|4|0010'),
            'wrong_end_count': trace().replace('|END|87|0', '|END|86|0'),
            'duplicate_end': trace() + '\n' + original[-1],
            'tb_error': trace().replace('|END|87|0', '|END|87|1'),
            'extra': trace() + '\n' + original[1],
            'spoof_inside': 'PASS\n' + trace().replace('|END|87|0', '|END|87|0\n@@RESULT@@{}'),
        }
        for name, stdout in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(verdict.judge(canned.COUNTER_OK, 'counter', NONCE,
                                                  sim(stdout))['verdict'], 'PASS')

    def test_stdout_pass_not_authoritative(self):
        self.assertNotEqual(verdict.judge(canned.COUNTER_OK, 'counter', NONCE,
                                          sim('PASS\nAll tests passed'))['verdict'], 'PASS')

    def test_exit_and_timeout_never_pass(self):
        for change in ({'rc': 1}, {'timeout': True}, {'stage': 'compile', 'compile_rc': 1},
                       {'stage': 'sandbox'}, {'compile_rc': None}):
            with self.subTest(change=change):
                self.assertNotEqual(verdict.judge(canned.COUNTER_OK, 'counter', NONCE,
                                                 sim(**change))['verdict'], 'PASS')

    def test_edited_oracle_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / 'trusted'
            for rel in verdict.PINNED_FILES | {'manifest.json'}:
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(verdict.TRUSTED / rel, dest / rel)
            (dest / 'oracle.py').write_text((dest / 'oracle.py').read_text() + '\n# unauthorized edit\n')
            with mock.patch.object(verdict, 'TRUSTED', dest):
                ok, _ = verdict.verify_manifest()
                self.assertFalse(ok)
                r = verdict.judge(canned.COUNTER_OK, 'counter', NONCE, sim())
                self.assertEqual(r['reason'], 'TRUSTED_ASSET_INTEGRITY_FAILURE')

    def test_manifest_bypass_forbidden_even_development(self):
        r = verdict.judge(canned.COUNTER_OK, 'counter', NONCE, sim(), skip_manifest=True)
        self.assertEqual(r['reason'], 'MANIFEST_BYPASS_FORBIDDEN')


class RunnerFrameTests(unittest.TestCase):
    def test_bad_transport_frames(self):
        good = '@@RESULT@@' + json.dumps({'stage': 'sim', 'ok': None, 'stdout': trace(), 'rc': 0,
                                           'compile_rc': 0})
        for out, rc, killed in [('PASS', 0, False),
                                ('@@RESULT@@{}@@RESULT@@{}', 0, False),
                                ('@@RESULT@@{bad}', 0, False),
                                ('X' + good, 0, False),
                                (good, 1, False),
                                (good, 0, True),
                                ('@@RESULT@@' + json.dumps({'stage':'sim', 'ok': True}), 0, False),
                                ('A' * 700_000, 0, False)]:
            with self.subTest(out=out[:40], rc=rc, killed=killed):
                r = sandbox._parse_result(out, '', rc, killed)
                self.assertFalse(r.get('stage') == 'sim' and r.get('ok') is None)
        self.assertEqual(sandbox._parse_result(good, '', 0, False)['stage'], 'sim')


class ConfigBudgetTests(unittest.TestCase):
    def test_production_downgrades_fail_on_startup(self):
        for flag in ('USE_LOCAL_SIM', 'SKIP_MANIFEST', 'MOCK_LLM'):
            with self.subTest(flag=flag), mock.patch.dict(os.environ, {
                'APP_ENV': 'production', flag: '1', 'APP_BASIC_USER': 'u',
                'APP_BASIC_PASSWORD': 'a' * 28}, clear=True):
                with self.assertRaises(RuntimeError):
                    config.validate_startup()

    def test_private_downgrades_fail_on_startup(self):
        for flag in ('USE_LOCAL_SIM', 'SKIP_MANIFEST'):
            with self.subTest(flag=flag), mock.patch.dict(os.environ, {
                'APP_ENV': 'private', 'MOCK_LLM': '1', flag: '1',
                'APP_BASIC_USER': 'u', 'APP_BASIC_PASSWORD': 'a' * 28}, clear=True):
                with self.assertRaises(RuntimeError):
                    config.validate_startup()

    def test_private_mock_requires_password(self):
        with mock.patch.dict(os.environ, {'APP_ENV': 'private', 'MOCK_LLM': '1'}, clear=True):
            with self.assertRaises(RuntimeError):
                config.validate_startup()
        with mock.patch.dict(os.environ, {'APP_ENV': 'private', 'MOCK_LLM': '1',
                                          'APP_BASIC_USER': 'u', 'APP_BASIC_PASSWORD': 'a'*32}, clear=True):
            config.validate_startup()

    def test_mock_health_and_private_basic_auth(self):
        import base64
        from fastapi.testclient import TestClient
        from app.main import app
        with mock.patch.dict(os.environ, {'APP_ENV': 'development', 'MOCK_LLM': '1'}, clear=True), \
             mock.patch('app.main.sandbox.docker_available', return_value=(False, 'not installed')):
            r = TestClient(app).get('/api/health')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['inference_mode'], 'MOCK')
            self.assertFalse(r.json()['sandbox_image_ready'])
        with mock.patch.dict(os.environ, {
            'APP_ENV': 'private', 'MOCK_LLM': '1',
            'APP_BASIC_USER': 'operator', 'APP_BASIC_PASSWORD': 'x'*32}, clear=True), \
             mock.patch('app.main.sandbox.docker_available', return_value=(False, 'not installed')):
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/health').status_code, 401)
                h = 'Basic ' + base64.b64encode(('operator:' + 'x'*32).encode()).decode()
                r = client.get('/api/health', headers={'Authorization': h})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()['inference_mode'], 'MOCK')

    def test_durable_inference_budget(self):
        with tempfile.TemporaryDirectory() as td:
            env = {'INFERENCE_LEDGER_PATH': str(Path(td) / 'budget.sqlite'),
                   'LIVE_INFERENCE_MAX_CALLS': '2'}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(budget.consume_one(), 1)
                self.assertEqual(budget.consume_one(), 0)
                with self.assertRaisesRegex(RuntimeError, 'EXHAUSTED'):
                    budget.consume_one()
                os.environ['LIVE_INFERENCE_MAX_CALLS'] = '3'
                with self.assertRaisesRegex(RuntimeError, 'CHANGE_REQUIRES'):
                    budget.consume_one()


if __name__ == '__main__':
    unittest.main()


class PublicMockSecurityTests(unittest.TestCase):
    def test_public_startup_restrictions(self):
        env = {'APP_ENV':'public_mock', 'PUBLIC_BIND_HOST':'0.0.0.0',
               'PUBLIC_MOCK_ACK':'1', 'MOCK_LLM':'1'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(config, 'require_rootless') as rootless:
            config.validate_startup()
            rootless.assert_called_once()
            for flag in ('USE_LOCAL_SIM', 'SKIP_MANIFEST'):
                with self.subTest(flag=flag), mock.patch.dict(os.environ, {flag:'1'}):
                    with self.assertRaises(RuntimeError): config.validate_startup()
            for bad in ({'MOCK_LLM':'0'}, {'VULTR_INFERENCE_API_KEY':'secret'},
                        {'PUBLIC_BIND_HOST':'127.0.0.1'}, {'PUBLIC_MOCK_ACK':'0'},
                        {'PUBLIC_MAX_ACTIVE_JOBS':'30'}):
                with self.subTest(bad=bad), mock.patch.dict(os.environ, bad):
                    with self.assertRaises(RuntimeError): config.validate_startup()

    def test_public_http_only_fixed_demo_ids(self):
        from fastapi.testclient import TestClient
        from app.main import app, _hits, _global_hits, _global_reads
        env = {'APP_ENV':'public_mock', 'PUBLIC_BIND_HOST':'0.0.0.0',
               'PUBLIC_MOCK_ACK':'1', 'MOCK_LLM':'1', 'PUBLIC_RATE_LIMIT_PER_MIN':'12'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch('app.main.agent.start', return_value={'id':'x','family':'counter'}) as start, \
             mock.patch('app.main.sandbox.docker_available', return_value=(False,'no Docker')):
            _hits.clear(); _global_hits.clear(); _global_reads.clear()
            with TestClient(app) as c:
                for path in ('/docs','/openapi.json','/redoc'):
                    self.assertEqual(c.get(path).status_code, 404)
                self.assertEqual(c.post('/api/probe').status_code,404)
                for payload in ({'request':'arbitrary RTL'},
                                {'demo_id':'counter','request':'malicious'},
                                {'demo_id':'unknown'},
                                {'demo_id':'counter','family':'counter'},
                                {'demo_id':'counter','request':''}):
                    with self.subTest(payload=payload):
                        self.assertIn(c.post('/api/jobs',json=payload).status_code,(400,422))
                self.assertEqual(c.post('/api/jobs',json={'demo_id':'counter'}).status_code,200)
                start.assert_called_once_with(canned.DEMOS[0]['prompt'],public_demo_id='counter')
                self.assertEqual(c.post('/api/jobs', content=b'x' * 2000,
                                        headers={'Content-Type': 'application/json'}).status_code, 413)
                self.assertEqual(c.get('/api/health').json()['inference_mode'],'MOCK')

    def test_public_concurrency_cap(self):
        from app import agent
        env = {'APP_ENV':'public_mock','MOCK_LLM':'1'}
        with mock.patch.dict(os.environ, env, clear=True):
            # Use a separate exhausted semaphore so no worker is launched.
            import threading
            sem = threading.BoundedSemaphore(1)
            sem.acquire()
            with mock.patch.object(agent, '_public_slots', sem):
                with self.assertRaises(agent.JobCapacityError):
                    agent.start(canned.DEMOS[0]['prompt'], public_demo_id='counter')
            with self.assertRaises(ValueError):
                agent.start('arbitrary RTL', public_demo_id='counter')

    def test_public_rate_limit(self):
        from fastapi.testclient import TestClient
        from app.main import app, _hits, _global_hits, _global_reads
        env = {'APP_ENV':'public_mock', 'MOCK_LLM':'1',
               'PUBLIC_RATE_LIMIT_PER_MIN':'2', 'PUBLIC_GLOBAL_LIMIT_PER_MIN':'3'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch('app.main.agent.start', return_value={'id':'x','family':'counter'}) as start:
            _hits.clear(); _global_hits.clear(); _global_reads.clear()
            with TestClient(app) as c:
                self.assertEqual(c.post('/api/jobs',json={'demo_id':'counter'}).status_code,200)
                self.assertEqual(c.post('/api/jobs',json={'demo_id':'counter'}).status_code,200)
                self.assertEqual(c.post('/api/jobs',json={'demo_id':'counter'}).status_code,429)
                self.assertEqual(c.get('/api/demos').status_code,200)  # GET quota separate
            self.assertEqual(start.call_count,2)

    def test_pinned_images_and_container_label(self):
        from app import docker_wrapper
        root = Path(__file__).resolve().parent.parent
        self.assertIn('FROM debian:bookworm-slim@sha256:99c0', (root/'sandbox/Dockerfile').read_text())
        self.assertIn('FROM python:3.12-slim-bookworm@sha256:e697', (root/'Dockerfile').read_text())
        self.assertIn('11.0-1.1', (root/'VERSIONS').read_text())
        flags = docker_wrapper._flags('vsbx-0123456789ab')
        self.assertIn('verilog-agent=1', flags)
        self.assertNotIn('-v', flags)
        self.assertIn('SENTINEL_VISIBLE=0', (root/'scripts/real_sandbox_regression.py').read_text())
        self.assertIn('verilog-agent-host-sentinel/token', (root/'trusted/chaos_tb.sv').read_text())
