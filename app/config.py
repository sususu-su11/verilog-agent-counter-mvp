"""Fail-closed startup policy for private, live-production and public MOCK modes."""
from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import urlparse


def enabled(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'yes', 'true', 'on')


def mode() -> str:
    return os.environ.get('APP_ENV', 'development').strip().lower()


def public_mock() -> bool:
    return mode() == 'public_mock'


def public_limits() -> tuple[int, int, int]:
    """Bound resource usage even if an operator enters unreasonable settings."""
    values = (int(os.environ.get('PUBLIC_RATE_LIMIT_PER_MIN', '6')),
              int(os.environ.get('PUBLIC_GLOBAL_LIMIT_PER_MIN', '60')),
              int(os.environ.get('PUBLIC_MAX_ACTIVE_JOBS', '2')))
    if not (1 <= values[0] <= 30 and 1 <= values[1] <= 300 and 1 <= values[2] <= 2):
        raise RuntimeError('unsafe public MOCK rate/concurrency limits')
    return values


def require_rootless() -> None:
    import subprocess
    try:
        info = subprocess.run(['docker', 'info', '--format', '{{json .SecurityOptions}}'],
                              capture_output=True, text=True, timeout=6, check=True)
        if 'rootless' not in info.stdout.lower():
            raise RuntimeError('Docker daemon is not rootless')
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('cannot prove rootless Docker daemon') from exc


def validate_startup() -> None:
    m = mode()
    if m not in ('development', 'private', 'production', 'public_mock'):
        raise RuntimeError('APP_ENV must be development/private/production/public_mock')
    from trusted.verdict import verify_manifest
    try:
        ok, _ = verify_manifest()
    except Exception as exc:
        raise RuntimeError('trusted manifest invalid') from exc
    if not ok:
        raise RuntimeError('trusted manifest hash mismatch')
    if m == 'development':
        return
    if enabled('USE_LOCAL_SIM') or enabled('SKIP_MANIFEST'):
        raise RuntimeError('restricted deployment disallows USE_LOCAL_SIM and SKIP_MANIFEST')
    if enabled('REQUIRE_GVISOR') and os.environ.get('SANDBOX_RUNTIME') != 'runsc':
        raise RuntimeError('REQUIRE_GVISOR needs SANDBOX_RUNTIME=runsc')
    if m == 'public_mock':
        if not enabled('MOCK_LLM') or os.environ.get('VULTR_INFERENCE_API_KEY', '').strip():
            raise RuntimeError('public_mock requires MOCK_LLM=1 and no inference credentials')
        if os.environ.get('PUBLIC_BIND_HOST', '127.0.0.1') != '0.0.0.0':
            raise RuntimeError('public_mock requires explicit public bind host')
        if not enabled('PUBLIC_MOCK_ACK'):
            raise RuntimeError('public_mock requires operator PUBLIC_MOCK_ACK=1')
        public_limits()
        # Public fixed-MOCK demonstrations may use an explicitly selected
        # rootful Docker socket on a disposable VM. This is an operator-accepted
        # control-plane risk, NOT equivalent to rootless isolation. Keep all
        # other public input, credential, downgrade and rate-limit gates.
        return
    password = os.environ.get('APP_BASIC_PASSWORD', '')
    if (not os.environ.get('APP_BASIC_USER') or len(password) < 24 or
            password.startswith('REPLACE_WITH_') or password.lower().startswith('changeme')):
        raise RuntimeError('private/production require APP_BASIC_USER and 24+ character password')
    if m == 'production' and (enabled('MOCK_LLM') or not os.environ.get('VULTR_INFERENCE_API_KEY')):
        raise RuntimeError('production requires genuine Vultr inference; mock forbidden')
    if m == 'production':
        require_rootless()
    if not enabled('MOCK_LLM') and os.environ.get('VULTR_INFERENCE_API_KEY'):
        u = urlparse(os.environ.get('VULTR_INFERENCE_BASE_URL', 'https://api.vultrinference.com/v1'))
        if u.scheme != 'https' or u.hostname != 'api.vultrinference.com':
            raise RuntimeError('live LLM endpoint must be Vultr HTTPS')
        if int(os.environ.get('LIVE_INFERENCE_MAX_CALLS', '0')) <= 0:
            raise RuntimeError('live inference needs explicit positive request cap')
        ledger = os.environ.get('INFERENCE_LEDGER_PATH', '')
        if not ledger or not Path(ledger).parent.is_dir():
            raise RuntimeError('live inference needs persistent, writable ledger directory')


def require_localhost_binding() -> None:
    if mode() in ('private', 'production') and os.environ.get('PUBLIC_BIND_HOST', '127.0.0.1') != '127.0.0.1':
        raise RuntimeError('private deploy binds loopback')
