#!/usr/bin/env python3
"""HTTP public MOCK smoke assertions; requires real running service/Docker."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.environ.get('PUBLIC_MOCK_TEST_URL', 'http://127.0.0.1:8000')

def request(path, payload=None):
    b = None if payload is None else json.dumps(payload).encode()
    try:
        with urlopen(Request(BASE+path, data=b,
                            headers={'Content-Type':'application/json'}), timeout=10) as r:
            return r.status, json.loads(r.read(100_000))
    except HTTPError as err:
        return err.code, {}


def main():
    code, health = request('/api/health')
    assert code == 200 and health['app_env'] == 'public_mock' and health['inference_mode'] == 'MOCK'
    for p in ('/docs', '/openapi.json', '/redoc'):
        assert request(p)[0] == 404
    for bad in ({'request':'arbitrary code'}, {'demo_id':'counter','request':'inject'},
                {'demo_id':'unknown'}):
        assert request('/api/jobs', bad)[0] in (400, 422)
    assert request('/api/probe', {})[0] == 404
    code, job = request('/api/jobs', {'demo_id':'counter'})
    assert code == 200 and 'id' in job
    print('PUBLIC_MOCK_HTTP_RESTRICTIONS_CHECKED; job started; verdict remains host-only:', job['id'])

if __name__ == '__main__':
    main()
