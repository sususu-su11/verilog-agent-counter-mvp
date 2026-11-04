"""'Try to break out' probes. Each probe attempts something a malicious generated program might
do and reports whether the sandbox CONTAINED it. Run with mode=probe."""
import os, socket, subprocess, sys

PROBE_TIMEOUT = 8


def _sub(code, timeout=PROBE_TIMEOUT):
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-400:]
    except subprocess.TimeoutExpired:
        return -9, "timed out"


def network():
    try:
        s = socket.create_connection(("1.1.1.1", 443), timeout=3)
        s.close()
        return False, "connected to 1.1.1.1:443 (!)"
    except OSError as e:
        return True, f"blocked: {e}"


def dns():
    try:
        ip = socket.gethostbyname("api.vultrinference.com")
        return False, f"resolved to {ip} (!)"
    except OSError as e:
        return True, f"blocked: {e}"


def secrets():
    leaked = [k for k in os.environ if any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET", "PASS"))]
    if leaked:
        return False, f"secret-looking env vars visible: {leaked}"
    return True, f"no secret-looking env vars ({len(os.environ)} vars total)"


def rootfs_write():
    try:
        with open("/usr/bin/pwned", "w") as f:
            f.write("x")
        return False, "wrote /usr/bin/pwned (!)"
    except OSError as e:
        return True, f"blocked: {e.strerror}"


def privilege():
    uid = os.getuid()
    try:
        os.setuid(0)
        return False, "setuid(0) succeeded (!)"
    except OSError as e:
        return uid != 0, f"uid={uid}; setuid(0): {e.strerror}"


def docker_socket():
    for p in ("/var/run/docker.sock", "/run/docker.sock"):
        if os.path.exists(p):
            return False, f"{p} is visible (!)"
    return True, "no docker socket mounted"


def memory_bomb():
    rc, out = _sub("b=[]\nfor i in range(64): b.append(bytearray(64*1024*1024))\nprint('allocated 4GB')")
    if "allocated" in out:
        return False, "allocated 4 GB (!)"
    return True, f"killed/limited (rc={rc}) {out.strip()[-120:]}"


def fork_bomb():
    code = ("import subprocess,sys\nps=[]\n"
            "try:\n for i in range(500): ps.append(subprocess.Popen(['sleep','5']))\n"
            " print('spawned',len(ps))\nexcept Exception as e: print('stopped at',len(ps),type(e).__name__)")
    rc, out = _sub(code)
    if "spawned 500" in out:
        return False, "spawned 500 processes (!)"
    return True, out.strip()[-160:]


def host_sentinel():
    # Host regression establishes this file EXISTS on the host at the same
    # time. It must NOT be visible inside sandbox's separate /tmp tmpfs.
    path = "/tmp/verilog-agent-host-sentinel/token"
    try:
        with open(path, "rb") as f:
            f.read(1)
        return False, "host sentinel readable inside sandbox (!)"
    except FileNotFoundError:
        return True, "host-only sentinel path absent in sandbox"
    except OSError as exc:
        return True, f"host sentinel not readable: {type(exc).__name__}"


def tmpfs_fill():
    rc, out = _sub("f=open('/work/fill','wb')\ntry:\n for i in range(1024): f.write(b'0'*1024*1024)\n print('wrote 1GB')\n"
                   "except OSError as e: print('stopped:', e.strerror)")
    try:
        os.remove("/work/fill")
    except OSError:
        pass
    if "wrote 1GB" in out:
        return False, "wrote 1 GB to scratch (!)"
    return True, out.strip()[-160:]


PROBES = [
    ("Outbound network (TCP 1.1.1.1:443)", network),
    ("DNS lookup", dns),
    ("Read API keys from environment", secrets),
    ("Write to root filesystem", rootfs_write),
    ("Escalate to root", privilege),
    ("Reach Docker socket", docker_socket),
    ("Memory bomb (4 GB)", memory_bomb),
    ("Fork bomb (500 procs)", fork_bomb),
    ("Fill scratch disk (1 GB)", tmpfs_fill),
    ("Host-only sentinel isolation", host_sentinel),
]


def run_all():
    results = []
    for name, fn in PROBES:
        try:
            contained, detail = fn()
        except Exception as e:  # probe errors are inconclusive, not a successful containment
            contained, detail = False, f"INCONCLUSIVE {type(e).__name__}: {e}"
        results.append({"probe": name, "contained": bool(contained), "detail": detail})
    return {"ok": len(results) == len(PROBES) and all(p["contained"] for p in results),
            "stage": "probe", "probes": results}
