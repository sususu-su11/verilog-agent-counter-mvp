"""Agent loop: LLM emits dut.v only → sandbox sim with trusted TB → host verdict.py → self-heal ≤3."""
from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from pathlib import Path

from trusted import verdict as verdict_mod, preflight
from trusted.oracle import FAMILIES

from . import families, llm, prompts, sandbox, vcd, config

MAX_ATTEMPTS = max(1, min(4, int(os.environ.get("MAX_ATTEMPTS", "4"))))  # hard cap, 3 heals
MAX_REQUEST_CHARS = 2000
JOBS: dict = {}
_lock = threading.Lock()
SAMPLES = Path(__file__).resolve().parent.parent / "docs" / "samples"
PUBLIC_MAX_ACTIVE = int(os.environ.get('PUBLIC_MAX_ACTIVE_JOBS', '2'))
_public_slots = threading.BoundedSemaphore(PUBLIC_MAX_ACTIVE)


class JobCapacityError(RuntimeError):
    pass


def _event(job, kind, **data):
    with _lock:
        job["events"].append({"t": round(time.time() - job["started"], 2), "kind": kind, **data})


def _diag(res: dict, art: dict) -> str:
    parts = []
    reason = art.get("reason")
    parts.append(f"host_verdict={art.get('verdict')} reason={reason}")
    if art.get("lint_errors"):
        parts.append("lint: " + ", ".join(art["lint_errors"]))
    if art.get("interface_errors"):
        parts.append("interface: " + ", ".join(art["interface_errors"]))
    if reason == "COMPILE_ERROR":
        c = art.get("compile") or {}
        parts.append("compile stderr:\n" + (c.get("stderr", "") + c.get("stdout", ""))[-3000:])
    elif reason in ("ORACLE_MISMATCH", "PROTOCOL_ERROR", "SUITE_MISMATCH",
                    "RECORD_COUNT_MISMATCH", "UNEXPECTED_RECORD_TOTAL", "TB_ERROR"):
        parts.append("mismatches: " + str(art.get("mismatches", art.get("protocol", {})))[:2500])
        sim = res.get("sim") or {}
        parts.append("sim stdout (protocol lines only, truncated):\n" +
                     "\n".join(ln for ln in (res.get("stdout") or "").splitlines()
                               if ln.startswith("VLTB1|"))[:2500])
    elif reason in ("TIMEOUT", "SIM_EXIT_NONZERO", "RTL_POLICY_VIOLATION", "INVALID_INTERFACE"):
        parts.append((res.get("stderr") or "")[-1500:])
    return "\n\n".join(parts)


def _save_sample(job, attempt_rec, art):
    try:
        SAMPLES.mkdir(parents=True, exist_ok=True)
        jid = job["id"]
        (SAMPLES / f"{jid}_attempt{attempt_rec['attempt']}_verdict.json").write_text(
            __import__("json").dumps(art, indent=2)[:20000]
        )
        log = (attempt_rec.get("result") or {}).get("stdout") or ""
        (SAMPLES / f"{jid}_attempt{attempt_rec['attempt']}_sim.log").write_text(log[-50000:])
        if attempt_rec.get("wave"):
            png = vcd.render_png(
                attempt_rec["wave"],
                f"dut counter attempt {attempt_rec['attempt']} {art.get('verdict')}",
            )
            (SAMPLES / f"{jid}_attempt{attempt_rec['attempt']}_wave.png").write_bytes(png)
    except Exception:
        pass


def run(job):
    req = job["request"]
    fam = job["family"]
    if fam not in FAMILIES:
        job["status"] = "failed"
        _event(job, "error", msg=f"MVP currently supports family=counter only (got {fam})")
        _event(job, "done", msg="aborted")
        return

    family_spec = families.family_spec_text(fam)
    messages = [
        {"role": "system", "content": prompts.SYSTEM},
        {"role": "user", "content": prompts.USER_TEMPLATE.format(request=req, family_spec=family_spec)},
    ]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        _event(job, "llm", attempt=attempt,
               msg=f"Attempt {attempt}: asking model for dut.v only"
                   + (" (self-heal)" if attempt > 1 else ""))
        try:
            text, meta = llm.chat(messages, req, attempt)
            design = llm.parse_dut(text)
        except Exception as e:
            _event(job, "error", attempt=attempt,
                   msg=f"LLM error: {type(e).__name__}: {str(e)[:300]}")
            messages.append({
                "role": "user",
                "content": "Reply with ONLY a JSON object with keys rtl and notes. "
                           "Module must be named dut. Do not include a testbench.",
            })
            continue

        messages.append({"role": "assistant", "content": text})
        tb_src = (Path(__file__).resolve().parent.parent / "trusted" /
                  FAMILIES[fam]["tb_file"]).read_text()
        _event(job, "design", attempt=attempt, model=meta.get("model"), mock=meta.get("mock"),
               top="dut", rtl=design["rtl"], testbench=tb_src,
               notes=design["notes"], family=fam,
               inference_response_received=bool(meta.get("inference_response_received", False)))

        # PRE-FLIGHT MUST PRECEDE *ANY* run_sim / compiler invocation.
        gate = preflight.validate(design["rtl"], fam)
        nonce = secrets.token_hex(16)
        if not gate["ok"]:
            _event(job, "preflight_reject", attempt=attempt, reason=gate["reason"],
                   errors=gate["errors"][:8])
            res = {"rc": -1, "stdout": "", "stderr": "preflight rejected",
                   "stage": "preflight", "timeout": False}
            art = {"verdict": "FAIL", "reason": gate["reason"],
                   "errors": gate["errors"][:8], "observations_checked": 0}
        else:
            _event(job, "sandbox", attempt=attempt,
                   msg="Spawning throwaway sandbox: trusted TB + dut.v, --network=none, "
                       "read-only rootfs, fixed-argv docker wrapper")
            res = sandbox.run_sim(fam, design["rtl"], nonce)
            # Independent SECOND check after execution. No bypass from env.
            art = verdict_mod.judge(design["rtl"], fam, nonce, res)

        wave = None
        if res.get("vcd"):
            try:
                wave = vcd.parse(res["vcd"])
            except Exception as e:
                res.setdefault("notes", []).append(f"VCD parse failed: {e}")

        result = {
            "ok": art["verdict"] == "PASS",
            "stage": art.get("reason") or res.get("stage"),
            "verdict": art,
            "lint": res.get("lint"),
            "compile": res.get("compile"),
            "sim": res.get("sim"),
            "stdout": res.get("stdout"),
            "stderr": res.get("stderr"),
            "containment": res.get("containment"),
            "vcd_truncated": res.get("vcd_truncated", False),
        }
        attempt_rec = {"attempt": attempt, "design": design, "result": result, "wave": wave,
                       "nonce": nonce, "family": fam}
        with _lock:
            job["attempts"].append(attempt_rec)
        _event(job, "result", attempt=attempt, ok=result["ok"], stage=result["stage"],
               result=result, wave=wave, verdict=art["verdict"], reason=art.get("reason"))
        _save_sample(job, attempt_rec, art)

        if art["verdict"] == "PASS":
            job.update(status="passed", final_attempt=attempt)
            _event(job, "done", msg=f"HOST PASS on attempt {attempt} "
                                    f"(checked {art.get('observations_checked')} observations)")
            return

        if attempt < MAX_ATTEMPTS:
            log = _diag(res, art)
            _event(job, "heal", attempt=attempt,
                   msg=f"FAIL ({art.get('reason')}) — feeding host diagnostic back to model "
                       "(dut.v only; TB/oracle frozen)",
                   log=log[-2000:])
            messages.append({
                "role": "user",
                "content": prompts.HEAL_TEMPLATE.format(
                    attempt=attempt, stage=art.get("reason"), log=log),
            })

    job.update(status="failed")
    _event(job, "done", msg=f"Gave up after {MAX_ATTEMPTS} attempts (host still FAIL)")


def start(request: str, *, public_demo_id: str | None = None) -> dict:
    reserved_slot = False
    if config.public_mock():
        from .mock import DEMOS
        known = {d['id']: d['prompt'] for d in DEMOS}
        if public_demo_id not in known or request != known[public_demo_id]:
            raise ValueError('public mock accepts only fixed demo ID/prompt')
        if not _public_slots.acquire(blocking=False):
            raise JobCapacityError('public demo capacity exhausted')
        reserved_slot = True
    request = request.strip()[:MAX_REQUEST_CHARS]
    fam = families.detect_family(request)
    job = {
        "id": uuid.uuid4().hex[:10],
        "request": request,
        "family": fam if not fam.startswith("unsupported:") else fam,
        "status": "running",
        "events": [],
        "attempts": [],
        "started": time.time(),
        "mock": llm.mock_mode(),
        "model": llm.MODEL,
    }
    JOBS[job["id"]] = job
    if len(JOBS) > 200:
        for k in list(JOBS)[:50]:
            JOBS.pop(k, None)

    def _wrap():
        try:
            if job["family"].startswith("unsupported:"):
                job["status"] = "failed"
                which = job["family"].split(":", 1)[1]
                _event(job, "error",
                       msg=f"MVP ships counter first; '{which}' trusted TB is next — "
                           "try the 4-bit sync counter demo.")
                _event(job, "done", msg="aborted")
                return
            run(job)
        except Exception as e:
            job["status"] = "failed"
            _event(job, "error", msg=f"internal error: {type(e).__name__}: {e}")
            _event(job, "done", msg="aborted")
        finally:
            if reserved_slot:
                _public_slots.release()

    try:
        threading.Thread(target=_wrap, daemon=True).start()
    except BaseException:
        if reserved_slot:
            _public_slots.release()
        JOBS.pop(job['id'], None)
        raise
    return job
