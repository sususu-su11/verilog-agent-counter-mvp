"""Host-side oracle comparison. The ONLY authority for PASS/FAIL."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .lint_rtl import static_lint, validate_interface
from .oracle import FAMILIES, expected_counter_trace, load_counter_vectors

TRUSTED = Path(__file__).resolve().parent
PROTO = re.compile(
    r"^VLTB1\|([0-9a-f]{32}|MISSING)\|([A-Z]+)\|(.*)$"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


PINNED_FILES = frozenset({
    # Host authority and trusted test assets.
    'tb_counter.sv', 'vectors/counter.json', 'oracle.py', 'verdict.py',
    'lint_rtl.py', 'preflight.py', 'verify_manifest.py',
    # Control plane, transport and sandbox implementation also affect the trust boundary.
    '../app/agent.py', '../app/sandbox.py', '../app/docker_wrapper.py',
    '../app/config.py', '../app/llm.py', '../app/budget.py', '../app/main.py',
    '../sandbox/runner.py', '../sandbox/Dockerfile', '../Dockerfile',
    '../docker-compose.yml', '../deploy.sh',
    'chaos_tb.sv', '../sandbox/probe.py', '../VERSIONS',
    '../app/static/app.js', '../scripts/real_sandbox_regression.py',
    '../scripts/public_mock_accept.py', '../.dockerignore',
})
MAX_PROTOCOL_BYTES = 16_384
MAX_PROTOCOL_LINES = 100
MAX_PROTOCOL_LINE = 256


def verify_manifest() -> tuple[bool, dict]:
    """Check an exact set of reviewed files; never refresh pins here."""
    man = json.loads((TRUSTED / "manifest.json").read_text())
    files = man.get("files")
    if not isinstance(files, dict) or set(files) != PINNED_FILES:
        raise ValueError("manifest file set differs from reviewed baseline")
    if (man.get("version") != "counter4_sync_v1" or
            man.get("family") != "counter" or man.get("expected_records") != 87):
        raise ValueError("manifest metadata mismatch")
    got = {}
    for rel, expected in files.items():
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("invalid manifest digest")
        path = TRUSTED / rel
        got[rel] = sha256_file(path) if path.is_file() else None
    return all(got[k] == v for k, v in files.items()), {
        "expected": files, "got": got, "version": man["version"]
    }


def parse_protocol(sim_stdout: str, nonce: str) -> tuple[bool, dict]:
    """Parse bounded, ordered VLTB1 records; textual PASS has no authority."""
    bad, records, tberrs = [], [], []
    begin = end = None
    if not isinstance(sim_stdout, str) or len(sim_stdout.encode('utf-8')) > MAX_PROTOCOL_BYTES:
        return False, {"begin": None, "end": None, "records": [], "tberrs": [],
                       "protocol_errors": [("too_large", "stdout")], "line_count": 0}
    if '@@RESULT@@' in sim_stdout:
        return False, {'begin': None, 'end': None, 'records': [], 'tberrs': [],
                       'protocol_errors': [('nested_runner_marker', 'stdout')], 'line_count': 0}
    lines = [ln.strip() for ln in sim_stdout.splitlines() if ln.strip().startswith('VLTB1')]
    if len(lines) > MAX_PROTOCOL_LINES:
        bad.append(('too_many_protocol_lines', len(lines)))
    for idx, ln in enumerate(lines[:MAX_PROTOCOL_LINES]):
        if len(ln) > MAX_PROTOCOL_LINE:
            bad.append(('oversize_line', idx)); continue
        parts = ln.split('|')
        if len(parts) < 3 or parts[0] != 'VLTB1':
            bad.append(('malformed', idx)); continue
        _, n, kind, *rest = parts
        if n != nonce:
            bad.append(('nonce_mismatch', idx)); continue
        if begin is None and kind != 'BEGIN':
            bad.append(('missing_begin', idx)); continue
        if end is not None:
            bad.append(('after_end', idx)); continue
        if kind == 'BEGIN':
            if begin is not None or idx != 0 or len(rest) != 2:
                bad.append(('bad_begin', idx)); continue
            begin = {'family': rest[0], 'suite_id': rest[1]}
        elif kind == 'END':
            if len(rest) != 2 or any(not re.fullmatch(r'[0-9]{1,5}', x) for x in rest):
                bad.append(('bad_end', idx)); continue
            end = {'record_count': int(rest[0]), 'tb_error_count': int(rest[1])}
        elif kind in ('IN', 'PRE', 'POST'):
            if len(rest) != 5:
                bad.append(('bad_observation', idx)); continue
            case, step_s, signal, width_s, bits = rest
            if (case != 'main' or not re.fullmatch(r'(0|[1-9][0-9]{0,3})', step_s)
                    or not re.fullmatch(r'[1-9][0-9]?', width_s)
                    or not re.fullmatch(r'[a-z][a-z_0-9]{0,31}', signal)):
                bad.append(('bad_fields', idx)); continue
            width = int(width_s)
            if len(bits) != width or not re.fullmatch('[01]+', bits):
                bad.append(('xz_or_bad_bits', idx)); continue
            records.append({'kind': kind, 'case': case, 'step': int(step_s),
                            'signal': signal, 'width': width, 'bits': bits})
        elif kind == 'TBERR':
            tberrs.append({'code': rest[0] if rest else '?', 'index': idx})
        else:
            bad.append(('unknown_kind', idx))
    if len(lines) > MAX_PROTOCOL_LINES:
        bad.append(('line_overflow', len(lines)))
    info = {'begin': begin, 'end': end, 'records': records, 'tberrs': tberrs,
            'protocol_errors': bad[:20], 'line_count': len(lines)}
    return begin is not None and end is not None and not bad and not tberrs, info


def _bits_to_int(bits: str) -> int | None:
    if any(c not in "01" for c in bits):
        return None
    return int(bits, 2)


def compare_counter(info: dict, vectors: dict) -> tuple[bool, list[dict], int]:
    """Compare IN vs frozen vectors and PRE/POST vs independent oracle."""
    expect = expected_counter_trace(vectors)
    mismatches = []
    checked = 0

    # Index observations
    by = {}
    for r in info["records"]:
        key = (r["kind"], r["step"], r["signal"])
        if key in by:
            mismatches.append({"type": "duplicate", **r})
        by[key] = r

    for row in expect:
        step = row["step"]
        # IN rst / en
        for sig, val in (("rst", row["rst"]), ("en", row["en"])):
            rec = by.get(("IN", step, sig))
            checked += 1
            if not rec:
                mismatches.append({"type": "missing_in", "step": step, "signal": sig})
                continue
            got = _bits_to_int(rec["bits"])
            if got is None:
                mismatches.append({"type": "xz_in", "step": step, "signal": sig, "bits": rec["bits"]})
            elif got != val:
                mismatches.append({"type": "in_mismatch", "step": step, "signal": sig,
                                   "expected": val, "got": got})

        # PRE
        if step > 0:
            rec = by.get(("PRE", step, "count"))
            checked += 1
            if not rec:
                mismatches.append({"type": "missing_pre", "step": step})
            else:
                got = _bits_to_int(rec["bits"])
                if got is None:
                    mismatches.append({"type": "xz_pre", "step": step, "bits": rec["bits"]})
                elif got != row["pre"]:
                    mismatches.append({"type": "pre_mismatch", "step": step,
                                       "expected": row["pre"], "got": got})

        # POST
        rec = by.get(("POST", step, "count"))
        checked += 1
        if not rec:
            mismatches.append({"type": "missing_post", "step": step})
        else:
            got = _bits_to_int(rec["bits"])
            if got is None:
                mismatches.append({"type": "xz_post", "step": step, "bits": rec["bits"]})
            elif got != row["post"]:
                mismatches.append({"type": "post_mismatch", "step": step,
                                   "expected": row["post"], "got": got})

    # Extra unexpected records?
    expected_keys = set()
    for row in expect:
        expected_keys.add(("IN", row["step"], "rst"))
        expected_keys.add(("IN", row["step"], "en"))
        if row["step"] > 0:
            expected_keys.add(("PRE", row["step"], "count"))
        expected_keys.add(("POST", row["step"], "count"))
    for key in by:
        if key not in expected_keys:
            mismatches.append({"type": "unexpected", "key": list(key)})
    # Enforce exact field width/case/record sequence; no shuffled or partial transcript.
    ordered_keys = []
    for row in expect:
        step = row['step']
        ordered_keys.extend([('IN', step, 'rst'), ('IN', step, 'en')])
        if step > 0:
            ordered_keys.append(('PRE', step, 'count'))
        ordered_keys.append(('POST', step, 'count'))
    actual_keys = [(r['kind'], r['step'], r['signal']) for r in info['records']]
    if actual_keys != ordered_keys:
        mismatches.append({'type': 'wrong_order_or_key_set'})
    for r in info['records']:
        expected_width = 4 if r['signal'] == 'count' else 1
        if r['case'] != 'main' or r['width'] != expected_width:
            mismatches.append({'type': 'wrong_width_or_case', 'step': r['step'],
                               'signal': r['signal']})
    return (not mismatches), mismatches, checked


def judge(candidate_src: str, family: str, nonce: str, sim: dict,
          skip_manifest: bool = False) -> dict:
    """
    sim: {rc, stdout, stderr, timeout, seconds} from sandbox/local runner.
    Returns host verdict artifact. Ignores any PASS string in sim stdout.
    """
    if family not in FAMILIES:
        return {'verdict': 'FAIL', 'reason': 'FAMILY_NOT_IMPLEMENTED'}
    fam = FAMILIES[family]
    tb_path = TRUSTED / fam["tb_file"]
    vec_path = TRUSTED / fam["vector_file"]

    artifact = {
        "verdict": "FAIL",
        "family": family,
        "reason": None,
        "candidate_sha256": sha256_text(candidate_src),
        "testbench_sha256": sha256_file(tb_path) if tb_path.exists() else None,
        "vector_sha256": sha256_file(vec_path) if vec_path.exists() else None,
        "simulation_exit_code": sim.get("rc"),
        "timeout": bool(sim.get("timeout")),
        "observations_checked": 0,
        "mismatches": [],
        "nonce": nonce,
    }

    ok_lint, lint_errs = static_lint(candidate_src)
    if not ok_lint:
        artifact["reason"] = "RTL_POLICY_VIOLATION"
        artifact["lint_errors"] = lint_errs
        return artifact

    ok_if, if_errs = validate_interface(candidate_src, family)
    if not ok_if:
        artifact["reason"] = "INVALID_INTERFACE"
        artifact["interface_errors"] = if_errs
        return artifact

    if skip_manifest:
        artifact["reason"] = "MANIFEST_BYPASS_FORBIDDEN"
        return artifact
    try:
        ok_man, man_info = verify_manifest()
    except Exception as exc:
        artifact["reason"] = "TRUSTED_ASSET_INTEGRITY_FAILURE"
        artifact["manifest_error"] = type(exc).__name__
        return artifact
    artifact["manifest"] = man_info
    if not ok_man:
        artifact["reason"] = "TRUSTED_ASSET_INTEGRITY_FAILURE"
        return artifact

    if sim.get("timeout"):
        artifact["reason"] = "TIMEOUT"
        return artifact

    if sim.get("stage") == "compile" or (sim.get("compile_rc") not in (None, 0)):
        # compile failure path may set stage=compile without running sim
        if sim.get("compile_rc", 0) != 0 or sim.get("stage") == "compile":
            artifact["reason"] = "COMPILE_ERROR"
            artifact["compile"] = {
                "rc": sim.get("compile_rc", sim.get("rc")),
                "stdout": sim.get("compile_stdout", ""),
                "stderr": sim.get("compile_stderr", sim.get("stderr", "")),
            }
            return artifact

    if sim.get("timeout"):
        artifact["reason"] = "TIMEOUT"
        return artifact

    if sim.get("rc", 1) != 0 or sim.get("compile_rc") != 0 or sim.get("stage") != "sim":
        artifact["reason"] = "SIM_EXIT_NONZERO"
        return artifact

    ok_proto, info = parse_protocol(sim.get("stdout", ""), nonce)
    artifact["protocol"] = {
        "begin": info["begin"], "end": info["end"],
        "tberrs": info["tberrs"], "protocol_errors": info["protocol_errors"],
        "n_records": len(info["records"]),
    }
    if not ok_proto:
        artifact["reason"] = "PROTOCOL_ERROR"
        return artifact

    if info["begin"]["family"] != family or info["begin"]["suite_id"] != fam["suite_id"]:
        artifact["reason"] = "SUITE_MISMATCH"
        return artifact

    if info["end"]["record_count"] != len(info["records"]):
        artifact["reason"] = "RECORD_COUNT_MISMATCH"
        return artifact

    if info["end"]["record_count"] != fam["expected_records"]:
        artifact["reason"] = "UNEXPECTED_RECORD_TOTAL"
        artifact["expected_records"] = fam["expected_records"]
        return artifact

    if info["end"]["tb_error_count"] != 0:
        artifact["reason"] = "TB_ERROR"
        return artifact

    vectors = load_counter_vectors() if family == "counter" else None
    if family != "counter":
        artifact["reason"] = "FAMILY_NOT_IMPLEMENTED"
        return artifact

    ok_cmp, mismatches, checked = compare_counter(info, vectors)
    artifact["observations_checked"] = checked
    artifact["mismatches"] = mismatches[:40]  # bound size
    artifact["mismatch_count"] = len(mismatches)
    if not ok_cmp:
        artifact["reason"] = "ORACLE_MISMATCH"
        return artifact

    artifact["verdict"] = "PASS"
    artifact["reason"] = "ORACLE_AGREEMENT"
    return artifact
