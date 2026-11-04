"""Fixed-argv Docker launcher for the Verilog sandbox.

The FastAPI process must NEVER construct arbitrary docker argv from user input.
This wrapper only permits:
  - run_sandbox(): docker run with a hard-coded containment profile + sandbox image
  - inspect_image(): docker image inspect of the configured sandbox image
  - force_rm(): docker rm -f of names matching ^vsbx-[0-9a-f]{12}$

No shell=True. No bind mounts. No secret env into the sandbox.
Prefer rootless Docker for the service account in production (see README Containment).
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from dataclasses import dataclass

DOCKER = os.environ.get("DOCKER_BIN", "docker")
IMAGE = os.environ.get("SANDBOX_IMAGE", "verilog-sandbox:latest")
MEM = os.environ.get("SANDBOX_MEMORY", "256m")
CPUS = os.environ.get("SANDBOX_CPUS", "0.5")
PIDS = os.environ.get("SANDBOX_PIDS", "64")
RUNTIME = os.environ.get("SANDBOX_RUNTIME", "").strip()
NAME_RE = re.compile(r"^vsbx-[0-9a-f]{12}$")


@dataclass
class RunResult:
    stdout: str
    stderr: str
    returncode: int
    name: str
    killed_by_wall: bool
    cleanup_verified: bool = False


def _flags(name: str) -> list[str]:
    flags = [
        "--rm", "--name", name,
        "--network", "none",
        "--memory", MEM, "--memory-swap", MEM,
        "--cpus", CPUS,
        "--pids-limit", PIDS,
        "--read-only",
        "--tmpfs", "/work:rw,exec,nosuid,nodev,size=16m,uid=65534,gid=65534",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m,uid=65534,gid=65534",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--ulimit", "nofile=256:256",
        "--ulimit", "fsize=20000000:20000000",
        "--env", "HOME=/work",
        "--label", "verilog-agent.sandbox=1",
        "--label", "verilog-agent=1",
        "-i",
    ]
    if RUNTIME:
        flags += ["--runtime", RUNTIME]
    return flags


def force_rm(name: str) -> bool:
    """Verify no matching sandbox container remains after both success and failure."""
    if not NAME_RE.fullmatch(name):
        raise ValueError(f'refusing to rm non-sandbox name: {name!r}')
    subprocess.run([DOCKER, 'rm', '-f', name], capture_output=True, text=True, timeout=10)
    p = subprocess.run([DOCKER, 'ps', '-aq', '--filter', f'name=^{name}$'],
                       capture_output=True, text=True, timeout=10)
    return p.returncode == 0 and not p.stdout.strip()


def run_sandbox(stdin_text: str, wall_seconds: int) -> RunResult:
    name = f'vsbx-{uuid.uuid4().hex[:12]}'
    cmd = [DOCKER, 'run', *_flags(name), IMAGE]
    result = RunResult('', '', -1, name, False)
    try:
        try:
            p = subprocess.run(cmd, input=stdin_text, capture_output=True,
                               text=True, timeout=wall_seconds)
            result.stdout, result.stderr, result.returncode = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            result.killed_by_wall = True
            result.stdout = e.stdout.decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
            result.stderr = e.stderr.decode(errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or '')
            result.returncode = -9
    except Exception as exc:
        result.stderr = f'Docker launcher failure: {type(exc).__name__}: {exc}'
    finally:
        try:
            result.cleanup_verified = force_rm(name)
        except Exception as exc:
            result.cleanup_verified = False
            result.stderr += f'; cleanup verification error: {type(exc).__name__}'
    if not result.cleanup_verified:
        result.returncode = -1
        result.stderr += '; sandbox cleanup not verified'
    return result


def inspect_image() -> tuple[bool, str]:
    try:
        p = subprocess.run([DOCKER, "image", "inspect", IMAGE],
                           capture_output=True, text=True, timeout=10)
        return p.returncode == 0, (p.stderr.strip()[-300:] or "ok")
    except Exception as e:
        return False, str(e)


def containment_meta(name: str, wall: int, sim_seconds: int) -> dict:
    return {
        "container": name, "image": IMAGE, "network": "none", "memory": MEM,
        "cpus": CPUS, "pids_limit": PIDS, "wall_seconds": wall,
        "sim_seconds": sim_seconds, "rootfs": "read-only",
        "user": "65534 (nobody)", "caps": "all dropped",
        "mounts": "none (tmpfs only)", "secrets": "none",
        "runtime": RUNTIME or "runc",
        "launcher": "docker_wrapper.fixed_argv",
    }
