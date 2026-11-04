#!/usr/bin/env python3
"""Operator-only local HTTP E2E. Requires running private VM with Docker and MOCK_LLM=1.

Uses actual Icarus-in-Docker simulation; never treats this helper as an independent judge.
"""
from __future__ import annotations
import base64
import json
import os
import sys
import time
from urllib.request import Request, urlopen

BASE = f"http://127.0.0.1:{os.environ.get('PUBLIC_PORT', '8000')}"
USER = os.environ.get('APP_BASIC_USER', '')
PASS = os.environ.get('APP_BASIC_PASSWORD', '')


def call(path, payload=None):
    headers = {'Authorization': 'Basic ' + base64.b64encode(f'{USER}:{PASS}'.encode()).decode()}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    with urlopen(Request(BASE + path, data=data, headers=headers), timeout=10) as response:
        return json.loads(response.read(512_000))


def job(prompt):
    j = call('/api/jobs', {'request': prompt, 'family': 'counter'})
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        time.sleep(0.7)
        r = call('/api/jobs/' + j['id'])
        if r['status'] != 'running':
            return r
    raise RuntimeError('job status timeout')


def check():
    h = call('/api/health')
    assert h['mock_llm'] is True, 'this test must not spend real Vultr inference credit'
    assert h['inference_mode'] == 'MOCK'
    assert h['sandbox_image_ready'] and not h['local_sim'], 'Docker sandbox required'
    for prompt, expected in (
        ('4-bit synchronous counter with enable', ['ORACLE_AGREEMENT']),
        ('demo self-heal: broken 4-bit counter that forgets enable (then fix)',
         ['ORACLE_MISMATCH', 'ORACLE_AGREEMENT']),
    ):
        r = job(prompt)
        reasons = [e.get('reason') for e in r['events'] if e['kind'] == 'result']
        assert reasons == expected, (prompt, reasons)
        assert r['status'] == 'passed' and r['mock'] is True
        assert all(e.get('result', {}).get('containment', {}).get('destroyed')
                   for e in r['events'] if e['kind'] == 'result')
        print('MOCK_DOCKER_E2E:', ' -> '.join(reasons), 'job', r['id'])
    return 0


if __name__ == '__main__':
    if not USER or not PASS:
        sys.exit('Configure APP_BASIC_USER and APP_BASIC_PASSWORD (private VM)')
    try:
        sys.exit(check())
    except Exception as exc:
        print('PRIVATE_ACCEPT_NOT_ESTABLISHED:', repr(exc), file=sys.stderr)
        sys.exit(1)
