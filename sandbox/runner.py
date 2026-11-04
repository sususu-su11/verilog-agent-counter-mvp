"""Sandbox entrypoint. Reads one JSON job from stdin, prints one JSON result to stdout.

Modes:
  sim   — compile trusted TB + dut.v, run vvp with +nonce=...; return raw logs (NO PASS judging)
  probe — containment self-tests

Never decides PASS/FAIL from textual claims. Host-side verdict.py is the authority.
"""
import glob, json, os, re, subprocess, sys, time

MAX_OUT = 80_000
MAX_INPUT_BYTES = 60_000
MAX_VCD = 400_000
SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,40}\.(v|sv|vh)$")


def run(cmd, timeout):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd="/work", capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout[-MAX_OUT:], p.stderr[-MAX_OUT:], False, time.time() - t0
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"")
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        return -9, out[-MAX_OUT:], f"TIMEOUT after {timeout}s (inner limit)", True, time.time() - t0


def sim(job):
    files = job.get("files", {})
    if (not isinstance(files, dict) or set(files) != {'dut.v', 'tb_counter.sv'}
            or not all(isinstance(x, str) for x in files.values())
            or sum(len(x.encode('utf-8')) for x in files.values()) > 40_000
            or job.get('top') != 'tb_top'):
        return {'stage': 'input', 'ok': False, 'stderr': 'unexpected files/top/size',
                'compile_rc': -1, 'rc': -1, 'stdout': '', 'timeout': False}
    names = []
    for name, src in files.items():
        if not SAFE_NAME.match(name):
            return {"stage": "input", "ok": False, "stderr": f"rejected filename {name!r}",
                    "compile_rc": -1, "rc": -1, "stdout": "", "timeout": False}
        with open(os.path.join("/work", name), "w") as f:
            f.write(src)
        names.append(name)

    top = job.get("top", "tb_top")
    nonce = job.get("nonce", "")
    if not re.fullmatch(r"[0-9a-f]{32}", nonce or ""):
        return {"stage": "input", "ok": False, "stderr": "missing/invalid nonce",
                "compile_rc": -1, "rc": -1, "stdout": "", "timeout": False}

    t = int(job.get("sim_timeout", 5))
    res = {"stage": "compile", "ok": False, "stdout": "", "stderr": "", "rc": -1, "timeout": False}

    # Optional lint on dut.v only (informational)
    if job.get("lint", True) and "dut.v" in files:
        rc, out, err, to, dt = run(
            ["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME", "-Wno-MULTITOP", "dut.v"], 20)
        res["lint"] = {"rc": rc, "log": (out + err)[-MAX_OUT:], "seconds": round(dt, 2)}

    # Fixed compilation: trusted TB + candidate, top = tb_top
    srcs = [n for n in names if n.endswith((".v", ".sv"))]
    rc, out, err, to, dt = run(["iverilog", "-g2012", "-Wall", "-s", top, "-o", "sim.vvp", *srcs], 20)
    res["compile"] = {"rc": rc, "stdout": out, "stderr": err, "seconds": round(dt, 2)}
    res["compile_rc"] = rc
    res["compile_stdout"] = out
    res["compile_stderr"] = err
    if rc != 0:
        res.update(stage="compile", ok=False, rc=rc)
        return res

    rc, out, err, to, dt = run(["vvp", "-n", "sim.vvp", f"+nonce={nonce}"], t)
    res["sim"] = {"rc": rc, "stdout": out, "stderr": err, "timeout": to, "seconds": round(dt, 2)}
    res.update(stage="sim", rc=rc, stdout=out, stderr=err, timeout=to, seconds=round(dt, 2))

    vcds = sorted(glob.glob("/work/*.vcd"))
    if vcds:
        with open(vcds[0], errors="replace") as f:
            data = f.read(MAX_VCD + 1)
        res["vcd"] = data[:MAX_VCD]
        res["vcd_truncated"] = len(data) > MAX_VCD

    # Sandbox does NOT judge PASS. Host verdict.py does.
    res["ok"] = None
    return res


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('job input too large')
    job = json.loads(raw or b'{}')
    if not isinstance(job, dict):
        raise ValueError('job must be a JSON object')
    if job.get("mode") == "probe":
        import probe
        result = probe.run_all()
    else:
        result = sim(job)
    sys.stdout.write("@@RESULT@@" + json.dumps(result, separators=(',', ':')))


if __name__ == "__main__":
    sys.path.insert(0, "/opt")
    main()
