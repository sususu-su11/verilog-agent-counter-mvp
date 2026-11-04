#!/usr/bin/env python3
"""Private VM ONLY: real Docker, host oracle, host-only sentinel and chaos TB.

Do not treat this as self-issued certification; save console logs for independent review.
Run when no other verilog-agent sandbox jobs are active.
"""
from __future__ import annotations
import json
import os
import secrets
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from app import mock as canned, sandbox, docker_wrapper as dw
from trusted import preflight, verdict

ROOT = Path(__file__).resolve().parent.parent
SENTINEL_DIR = Path('/tmp/verilog-agent-host-sentinel')
SENTINEL = SENTINEL_DIR / 'token'


@contextmanager
def host_only_sentinel():
    # Never overwrite an existing user's sentinel.
    SENTINEL_DIR.mkdir(mode=0o700, exist_ok=False)
    token = secrets.token_hex(32)
    try:
        SENTINEL.write_text(token, encoding='ascii')
        os.chmod(SENTINEL, 0o600)
        yield token
        assert SENTINEL.read_text() == token, 'host sentinel modified!'
    finally:
        SENTINEL.unlink(missing_ok=True)
        SENTINEL_DIR.rmdir()


def assert_no_labeled_containers():
    p = subprocess.run([dw.DOCKER, 'ps', '-aq', '--filter', 'label=verilog-agent=1'],
                       capture_output=True, text=True, timeout=10, check=True)
    if p.stdout.strip():
        raise RuntimeError('unremoved labeled sandbox containers: ' + p.stdout.strip())
    print('SANDBOX_LABEL_CLEANUP: no label=verilog-agent=1 containers remain')


def run_one(label: str, rtl: str, expect: str | set[str]):
    gate = preflight.validate(rtl, 'counter')
    if not gate['ok']:
        raise RuntimeError(f'{label} preflight rejected: {gate}')
    nonce = secrets.token_hex(16)
    raw = sandbox.run_sim('counter', rtl, nonce)
    out = verdict.judge(rtl, 'counter', nonce, raw)
    print(f'{label}: host={out["verdict"]} reason={out["reason"]} '
          f'checked={out.get("observations_checked")} '
          f'cleanup={raw.get("containment", {}).get("destroyed")}')
    expected_reasons = {expect} if isinstance(expect, str) else expect
    expected_verdict = 'PASS' if expected_reasons == {'ORACLE_AGREEMENT'} else 'FAIL'
    if (out['reason'] not in expected_reasons or out['verdict'] != expected_verdict
            or not raw.get('containment', {}).get('destroyed')):
        raise RuntimeError(f'{label} unexpected host result/cleanup')
    assert_no_labeled_containers()


def probe_and_chaos(token: str):
    # Probe runs in the same isolated image/flags; no socket, host token or mounts.
    result = sandbox.run_probe()
    checks = {x['probe']: x for x in result.get('probes', [])}
    sentinel_name = 'Host-only sentinel isolation'
    if (result.get('stage') != 'probe' or not result.get('ok') or
            sentinel_name not in checks or not checks[sentinel_name]['contained'] or
            len(checks) != 10 or not result.get('containment', {}).get('destroyed')):
        raise RuntimeError('containment/sentinel probes failed: ' + str(result)[:2000])
    assert SENTINEL.read_text() == token
    assert_no_labeled_containers()
    print('SENTINEL_PROBE: host token present, sandbox cannot read; 10/10 probes reported contained')

    # Deliberately evil *trusted regression TB* runs only via operator script.
    # This must never be accepted as a real counter TB / host PASS.
    nonce = secrets.token_hex(16)
    payload = {'mode': 'sim', 'top': 'tb_top', 'nonce': nonce, 'sim_timeout': 5,
               'lint': False,
               'files': {'dut.v': canned.COUNTER_OK,
                         'tb_counter.sv': (ROOT/'trusted/chaos_tb.sv').read_text()}}
    raw = dw.run_sandbox(json.dumps(payload), wall_seconds=30)
    if raw.returncode != 0 or not raw.cleanup_verified:
        raise RuntimeError('chaos runner/cleanup did not complete')
    if 'SENTINEL_VISIBLE=0' not in raw.stdout or 'SENTINEL_VISIBLE=1' in raw.stdout:
        raise RuntimeError('host sentinel visibility isolation not demonstrated')
    if token in raw.stdout or token in raw.stderr:
        raise RuntimeError('host sentinel value leaked into container output')
    parsed = sandbox._parse_result(raw.stdout, raw.stderr, raw.returncode, raw.killed_by_wall)
    assert parsed.get('stage') == 'sandbox', 'nested @@RESULT@@ must invalidate runner frame'
    art = verdict.judge(canned.COUNTER_OK, 'counter', nonce, parsed)
    assert art['verdict'] == 'FAIL', 'chaos TB forgery must never gain a host PASS'
    assert SENTINEL.read_text() == token
    assert_no_labeled_containers()
    print('CHAOS_TB: forged PASS/VLTB1/runner marker rejected; sentinel inaccessible; cleanup verified')


def main():
    if sandbox.USE_LOCAL:
        raise RuntimeError('USE_LOCAL_SIM cannot establish Docker isolation')
    ready, detail = sandbox.docker_available()
    if not ready:
        raise RuntimeError('Docker sandbox image missing: ' + detail)
    assert_no_labeled_containers()
    with host_only_sentinel() as token:
        run_one('counter good', canned.COUNTER_OK, 'ORACLE_AGREEMENT')
        run_one('counter bad enable', canned.COUNTER_BAD_EN, 'ORACLE_MISMATCH')
        async_reset = canned.COUNTER_OK.replace('always @(posedge clk)',
                                                'always @(posedge clk or posedge rst)')
        run_one('counter async reset', async_reset, 'ORACLE_MISMATCH')
        bad_wrap = canned.COUNTER_OK.replace("count <= count + 4'd1;",
                                             'count <= (count == 15) ? 15 : count + 1;')
        run_one('counter bad wrap', bad_wrap, 'ORACLE_MISMATCH')
        bad_x = canned.COUNTER_OK.replace("count <= 4'd0;", "count <= 4'bxxxx;")
        run_one('counter X output', bad_x, {'ORACLE_MISMATCH', 'PROTOCOL_ERROR'})
        malicious = canned.COUNTER_OK.replace('endmodule', '$display("PASS"); endmodule')
        assert not preflight.validate(malicious, 'counter')['ok']
        print('MALICIOUS_RTL: rejected by preflight before run_sim')
        probe_and_chaos(token)
    print('REGRESSION_FINISHED: review real VM evidence independently; no self-issued PASS')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('DOCKER_REGRESSION_NOT_ESTABLISHED:', repr(exc), file=sys.stderr)
        sys.exit(1)
