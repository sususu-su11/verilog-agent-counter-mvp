"""Run one verification job: trusted TB + candidate dut.v inside the locked-down sandbox.

PASS/FAIL is NOT decided here — host trusted/verdict.py is the authority.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from . import docker_wrapper as dw

TRUSTED = Path(__file__).resolve().parent.parent / "trusted"
WALL = int(os.environ.get("SANDBOX_WALL_SECONDS", "30"))
SIM_SECONDS = int(os.environ.get("SANDBOX_SIM_SECONDS", "5"))
MAX_PARALLEL = int(os.environ.get("SANDBOX_MAX_PARALLEL", "2"))
# Prefer docker; set USE_LOCAL_SIM=1 only for host-side bring-up (no containment).
USE_LOCAL = os.environ.get("USE_LOCAL_SIM", "").lower() in ("1", "true", "yes")

_slots = threading.BoundedSemaphore(MAX_PARALLEL)


def docker_available():
    return dw.inspect_image()


MAX_RUNNER_BYTES = 650_000
RUNNER_PREFIX = '@@RESULT@@'


def _parse_result(out: str, err: str, rc: int, killed: bool) -> dict:
    """Runner stdout is transport, not an authority; reject malformed frames."""
    def fail(why):
        return {'ok': False, 'stage': 'sandbox', 'stderr': why,
                'rc': -1, 'stdout': '', 'timeout': killed, 'compile_rc': -1}
    if killed or rc != 0:
        return fail('sandbox timeout' if killed else 'sandbox container nonzero exit')
    if len(out.encode('utf-8', errors='replace')) > MAX_RUNNER_BYTES:
        return fail('oversized runner frame')
    if not out.startswith(RUNNER_PREFIX) or out.count(RUNNER_PREFIX) != 1:
        return fail('missing/duplicate runner frame')
    try:
        data = json.loads(out[len(RUNNER_PREFIX):])
    except (ValueError, TypeError):
        return fail('unparseable sandbox result')
    if not isinstance(data, dict):
        return fail('runner result must be JSON object')
    if data.get('ok') is not None and data.get('stage') != 'probe':
        return fail('runner is not verdict authority')
    if not isinstance(data.get('stdout', ''), str):
        return fail('invalid simulator stdout')
    if len(data.get('stdout', '')) > 100_000:
        return fail('oversized simulator stdout')
    if data.get('stage') not in ('sim', 'compile', 'input', 'probe'):
        return fail('unknown runner stage')
    return data


def run_sim(family: str, dut_src: str, nonce: str) -> dict:
    """Compile trusted TB + dut.v and simulate. Returns raw sim dict + containment meta."""
    from trusted.oracle import FAMILIES
    fam = FAMILIES[family]
    tb_src = (TRUSTED / fam["tb_file"]).read_text()
    job = {
        "mode": "sim",
        "top": "tb_top",
        "nonce": nonce,
        "sim_timeout": SIM_SECONDS,
        "lint": True,
        "files": {
            "dut.v": dut_src,
            fam["tb_file"]: tb_src,
        },
    }
    t0 = time.time()
    with _slots:
        if USE_LOCAL:
            res = _local_sim(job)
            name = "local-sim"
            killed = bool(res.get("timeout"))
        else:
            raw = dw.run_sandbox(json.dumps(job), WALL)
            res = _parse_result(raw.stdout, raw.stderr, raw.returncode, raw.killed_by_wall)
            name, killed = raw.name, raw.killed_by_wall
    if USE_LOCAL:
        meta = {'container': 'local-sim', 'local': True,
                'launcher': 'UNCONTAINED_LOCAL_SIM', 'network': 'host',
                'rootfs': 'host', 'secrets': 'host environment', 'destroyed': False}
    else:
        meta = dw.containment_meta(name, WALL, SIM_SECONDS)
        meta.update(local=False, destroyed=raw.cleanup_verified)
    meta.update(seconds=round(time.time() - t0, 2),
                exit_code=res.get('rc'), killed_by_wall_clock=killed)
    res["containment"] = meta
    return res


def run_probe() -> dict:
    job = {"mode": "probe"}
    t0 = time.time()
    with _slots:
        raw = dw.run_sandbox(json.dumps(job), WALL)
        res = _parse_result(raw.stdout, raw.stderr, raw.returncode, raw.killed_by_wall)
        name, killed = raw.name, raw.killed_by_wall
    meta = dw.containment_meta(name, WALL, SIM_SECONDS)
    meta.update(seconds=round(time.time() - t0, 2), exit_code=raw.returncode,
                killed_by_wall_clock=killed, destroyed=raw.cleanup_verified)
    if isinstance(res, dict):
        res["containment"] = meta
    return res


def _local_sim(job: dict) -> dict:
    """Host iverilog path for bring-up when Docker image path is awkward. NOT for production."""
    import glob
    import subprocess

    with tempfile.TemporaryDirectory(prefix="vagent-") as td:
        td = Path(td)
        for name, src in job["files"].items():
            (td / name).write_text(src)
        srcs = sorted(p.name for p in td.glob("*.v")) + sorted(p.name for p in td.glob("*.sv"))
        compile_cmd = ["iverilog", "-g2012", "-Wall", "-s", job["top"], "-o", "sim.vvp", *srcs]
        try:
            p = subprocess.run(compile_cmd, cwd=td, capture_output=True, text=True, timeout=20)
        except FileNotFoundError:
            return {"stage": "sandbox", "ok": False, "stderr": "iverilog not installed on host",
                    "rc": -1, "stdout": "", "timeout": False, "compile_rc": -1}
        res = {
            "compile": {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr},
            "compile_rc": p.returncode,
            "compile_stdout": p.stdout,
            "compile_stderr": p.stderr,
        }
        if p.returncode != 0:
            res.update(stage="compile", ok=False, rc=p.returncode, stdout="", stderr=p.stderr, timeout=False)
            return res
        try:
            p2 = subprocess.run(
                ["vvp", "-n", "sim.vvp", f"+nonce={job['nonce']}"],
                cwd=td, capture_output=True, text=True, timeout=job.get("sim_timeout", 5),
            )
            to = False
            rc, out, err = p2.returncode, p2.stdout, p2.stderr
        except subprocess.TimeoutExpired as e:
            to = True
            rc = -9
            out = (e.stdout or "") if isinstance(e.stdout, str) else ""
            err = "TIMEOUT"
        res["sim"] = {"rc": rc, "stdout": out, "stderr": err, "timeout": to}
        res.update(stage="sim", rc=rc, stdout=out, stderr=err, timeout=to, ok=None)
        vcds = sorted(glob.glob(str(td / "*.vcd")))
        if vcds:
            data = Path(vcds[0]).read_text(errors="replace")
            res["vcd"] = data[:400_000]
            res["vcd_truncated"] = len(data) > 400_000
        return res
