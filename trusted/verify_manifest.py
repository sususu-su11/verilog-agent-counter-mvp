"""Read-only integrity gate for deploy, CI, preflight and app startup."""
from __future__ import annotations
import sys
from .verdict import verify_manifest


def main():
    try:
        ok, data = verify_manifest()
    except Exception as exc:
        print('MANIFEST_FAIL:', type(exc).__name__, str(exc), file=sys.stderr)
        return 1
    if not ok:
        for path, expected in data['expected'].items():
            if data['got'].get(path) != expected:
                print('MANIFEST_FAIL:', path, file=sys.stderr)
        return 1
    print('MANIFEST_OK:', data['version'], len(data['expected']), 'assets')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
