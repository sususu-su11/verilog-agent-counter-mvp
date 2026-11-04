"""Mandatory BEFORE-compile gate, independently repeated by verdict.judge."""
from __future__ import annotations
from .lint_rtl import static_lint, validate_interface
from .verdict import verify_manifest


def validate(src: str, family: str, *, check_manifest: bool = True) -> dict:
    ok, errs = static_lint(src)
    if not ok:
        return {'ok': False, 'reason': 'RTL_POLICY_VIOLATION', 'errors': errs}
    ok, errs = validate_interface(src, family)
    if not ok:
        return {'ok': False, 'reason': 'INVALID_INTERFACE', 'errors': errs}
    # No bypass for private/production, including via environment.
    if check_manifest:
        try:
            ok, detail = verify_manifest()
        except Exception as exc:
            return {'ok': False, 'reason': 'TRUSTED_ASSET_INTEGRITY_FAILURE',
                    'errors': [type(exc).__name__]}
        if not ok:
            return {'ok': False, 'reason': 'TRUSTED_ASSET_INTEGRITY_FAILURE',
                    'errors': ['manifest_hash_mismatch']}
    return {'ok': True, 'reason': 'PREFLIGHT_OK', 'errors': []}
