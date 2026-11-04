# Verilog Agent — Counter MVP (trusted verdict)

## Status and scope

Only `counter4_sync_v1` is implemented. Vultr Serverless Inference can propose `dut.v` in a **private operator-only** deployment; trusted host `verdict.py` and fixed `tb_counter.sv` exclusively determine PASS/FAIL. `MOCK_LLM=1` exercises canned example RTL and an intentional bad-enable self-heal sequence; **MOCK is never live Vultr evidence**. UART/FIFO/FSM are not implemented.

**This is not an audited public general-purpose RTL service.** The limited counter vectors do not establish formal correctness. Public demo mode is fixed MOCK cases only, not user code.

## Local/offline checks

```bash
python3 -m trusted.verify_manifest
python3 -m unittest discover -s tests -v
python3 -m compileall -q app sandbox trusted scripts tests
node --check app/static/app.js
bash -n deploy.sh
```

These tests use synthetic fixtures; they are **not** Docker isolation evidence or Icarus simulation. See `TEST_RESULTS.md`.

## Private VM deployment (no cloud resources created by these scripts)

Requires Docker + Compose on a dedicated disposable VM. Prefer an isolated **rootless** Docker daemon and inspect the selected socket. Provision VM manually **only if provider-level spending safeguards prevent charges outside remaining credit**; inference request count caps are not dollar caps.

```bash
cp .env.example .env
chmod 600 .env
# APP_ENV=private; PUBLIC_BIND_HOST=127.0.0.1; MOCK_LLM=1
# Set a strong APP_BASIC_PASSWORD and accurate DOCKER_HOST_SOCKET.
# USE_LOCAL_SIM=0; SKIP_MANIFEST=0.
./deploy.sh
ssh -L 8000:127.0.0.1:8000 operator@PRIVATE_VM_IP
```

Use Basic Auth on `http://127.0.0.1:8000` via SSH tunnel. Actual VM regression (must be run and recorded by operator):

```bash
set -a; . ./.env; set +a
python3 -m scripts.real_sandbox_regression
python3 -m scripts.private_accept
```

The real regression temporarily creates `/tmp/verilog-agent-host-sentinel/token` on **the host** (0600), runs the 10-probe containment suite and **trusted chaos TB** that tries to print forged `PASS`/`VLTB1`/`@@RESULT@@` strings and read the sentinel; it confirms cleanup of containers with `label=verilog-agent=1`. This script must run while no other verilog-agent sandbox jobs are active. The token is removed at completion. Without Docker/Icarus there is no real isolation proof.

## Public fixed MOCK mode — explicit opt-in only

This is a minimal public **demonstration**, not a public submission service. A dedicated disposable VM with **rootful Docker** (`/var/run/docker.sock`) is permitted for the fixed-MOCK demo; **rootless is recommended but not required in `public_mock`**. This is an explicit, higher-risk exception to the production policy, not evidence of Blast Radius Zero. Restrict inbound access at the firewall/edge, avoid host secrets or other workloads on this VM, and monitor costs. Set `.env` values:

```dotenv
APP_ENV=public_mock
PUBLIC_BIND_HOST=0.0.0.0
PUBLIC_MOCK_ACK=1
MOCK_LLM=1
VULTR_INFERENCE_API_KEY=
USE_LOCAL_SIM=0
SKIP_MANIFEST=0
DOCKER_HOST_SOCKET=/var/run/docker.sock
PUBLIC_RATE_LIMIT_PER_MIN=6
PUBLIC_GLOBAL_LIMIT_PER_MIN=60
PUBLIC_MAX_ACTIVE_JOBS=2
```

Then run **only** `./deploy.sh --public-mock`. Startup refuses missing opt-in, configured inference credentials and downgraded sandbox/manifest controls. In `public_mock` it **does not enforce rootless**; `production` still requires rootless. Direct `/api/jobs` calls must supply **only** `{ "demo_id": "counter" }` or `{ "demo_id": "counter_heal" }`; arbitrary requests, extra fields, unknown IDs and LLM-supplied RTL are rejected. `/docs`, `/redoc`, `/openapi.json` and `/api/probe` are disabled, with per-IP/global in-process throttles, active-job slots (max 2) and underlying sandbox parallel limit. UI text input is read-only and selected examples are sent by ID.

Check HTTP restrictions on the running public demo: `python3 -m scripts.public_mock_accept`. The public interface uses one Uvicorn worker (in-process rate limits are **not distributed**). Put additional request/body quotas and abuse protection at a trusted edge if publicly exposed. Do **not** accept proxy `X-Forwarded-For` as proof of client IP. Mounting a rootful Docker socket into the backend gives a compromised backend effectively host-root Docker authority. Fixed demo IDs, rate limits and sandbox flags **do not** protect against backend compromise; keep the VM disposable, isolated from sensitive resources, firewall-restricted and separately monitored. Never accept arbitrary user RTL in public MOCK mode.

## Known limits / security boundary

1. **Regex/static lint is not a complete SystemVerilog parser or sandbox.** It blocks known system tasks, `initial`, strings, directives, etc. before `run_sim`, but future grammar escapes and Icarus/Verilator parser vulnerabilities are not ruled out. Execute only in the restricted Docker container; keep tools patched. A genuine malicious RTL attempt must never be directly compiled on the host.
2. **Docker daemon socket** is mounted in the backend, not the sandbox. The fixed-argv wrapper constrains normal paths but backend RCE could access the daemon; rootless reduces but does not eliminate damage. **`public_mock` allows a rootful socket by operator choice; compromise of the backend on that VM may lead to host takeover.** Public demo reduces attacker-controlled inputs, does not prove blast radius zero. This is **not recommended for arbitrary untrusted Internet code**.
3. **Isolation evidence is empirical, not proof.** The 10 sandbox probes, host sentinel, chaos TB and labeled-container cleanup must run on the target VM. Until those run, containment status is unverified.
4. **Supply chain:** both base `FROM` images are pinned to *operator-provided* SHA256 values (see `VERSIONS`; validate on target VM). The backend Docker CLI `ADD` downloads a versioned tarball from a URL **without a verified content digest**, and Apt packages have only Debian repository version semantics. `iverilog` bookworm version is recorded as `11.0-1.1` but is not yet runtime-verified.
5. **Manifest:** `trusted/manifest.json` is part of the reviewed source. `deploy.sh` only checks hashes; changing the oracle without a separately reviewed manifest update fails. A Git-committed manifest is not a cryptographic signature.
6. **Costs:** no code controls Vultr's account/card billing. `LIVE_INFERENCE_MAX_CALLS` is a durable **call-count** breaker for private live use, not a money-based limit. No live Inference, paid VM deployment, public URL, video or LabLab submission is claimed here.

`LICENSE`: MIT. See `PATCH_REPORT_CN.md` for scope, acceptance boundaries, and `CREDIT_SAFETY.md` before using live inference.
