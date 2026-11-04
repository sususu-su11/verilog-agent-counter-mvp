"""Verilog Agent — FastAPI backend (counter-first trusted verification MVP)."""
from __future__ import annotations

import os
import base64
import binascii
import secrets
import sys
import time
import threading
from collections import defaultdict, deque
from pathlib import Path

# Project root on sys.path so `trusted` imports resolve
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict

from . import agent, llm, mock, sandbox, config

# Fail before the application begins serving HTTP requests.
config.validate_startup()

app = FastAPI(title="Verilog Agent", version="0.3.0",
              docs_url=None if config.public_mock() else '/docs',
              redoc_url=None if config.public_mock() else '/redoc',
              openapi_url=None if config.public_mock() else '/openapi.json')
STATIC = Path(__file__).parent / "static"
RATE = int(os.environ.get("RATE_LIMIT_PER_MIN", "6"))
_hits: dict = defaultdict(deque)
_global_hits = deque()
_global_reads = deque()
_hits_lock = threading.Lock()


def public_rate_gate(request: Request) -> bool:
    """In-process single-worker limiter; no XFF header trust. No external billing."""
    per_ip, global_max, _ = config.public_limits()
    is_write = request.method == 'POST'
    # Polling (GET) must not exhaust the create-job (POST) quota.
    max_ip = per_ip if is_write else 120
    max_all = global_max if is_write else 2000
    group = 'post' if is_write else 'read'
    key = (group, request.client.host if request.client else '?')
    now = time.monotonic()
    with _hits_lock:
        q = _hits[key]
        global_q = _global_hits if is_write else _global_reads
        for bucket in (q, global_q):
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
        if len(q) >= max_ip or len(global_q) >= max_all:
            return False
        q.append(now)
        global_q.append(now)
    return True


@app.middleware('http')
async def private_auth(request: Request, call_next):
    if config.public_mock():
        if request.url.path in ('/docs', '/redoc', '/openapi.json', '/api/probe'):
            return Response('Not found', status_code=404)
        if request.url.path.startswith('/api/'):
            if not public_rate_gate(request):
                return Response('Public demo rate limit reached', status_code=429)
            if request.method == 'POST' and request.url.path == '/api/jobs':
                # Cap body while streaming, even if Content-Length is omitted.
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 1024:
                        return Response('Request too large', status_code=413)
                    body.extend(chunk)
                request._body = bytes(body)  # Starlette's cached body for downstream FastAPI
    if config.mode() in ('private', 'production'):
        header = request.headers.get('authorization', '')
        allowed = False
        if header.startswith('Basic '):
            try:
                raw = base64.b64decode(header[6:], validate=True).decode('utf-8')
                user, password = raw.split(':', 1)
                allowed = (secrets.compare_digest(user, os.environ['APP_BASIC_USER']) and
                           secrets.compare_digest(password, os.environ['APP_BASIC_PASSWORD']))
            except (ValueError, UnicodeError, binascii.Error, KeyError):
                pass
        if not allowed:
            return Response('Authentication required', status_code=401,
                            headers={'WWW-Authenticate': 'Basic realm="Verilog Private VM"'})
    return await call_next(request)


def _ratelimit(request: Request):
    # Ignore untrusted X-Forwarded-For; default uvicorn does NOT trust proxy headers.
    ip = request.client.host if request.client else '?'
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE:
        raise HTTPException(429, "Too many runs — wait a minute.")
    q.append(now)


class RunReq(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request: str = Field(default='', max_length=2000)
    family: str | None = None
    demo_id: str | None = Field(default=None, max_length=40)


@app.get("/api/health")
def health():
    ok, detail = sandbox.docker_available()
    return {
        "ok": True,
        "sandbox_image_ready": ok,
        "detail": detail,
        "mock_llm": llm.mock_mode(),
        "inference_mode": "MOCK" if llm.mock_mode() else "LIVE_CONFIGURED_NOT_VERIFIED",
        "app_env": config.mode(),
        "model": "mock" if llm.mock_mode() else llm.MODEL,
        "base_url": llm.BASE_URL,
        "max_attempts": agent.MAX_ATTEMPTS,
        "families": ["counter"],
        "verification": "host trusted/verdict.py (LLM never owns PASS)",
        "launcher": "docker_wrapper.fixed_argv",
        "local_sim": sandbox.USE_LOCAL,
    }


@app.get("/api/demos")
def demos():
    return mock.DEMOS


@app.post("/api/jobs")
def create_job(body: RunReq, request: Request):
    if config.public_mock():
        if body.model_fields_set != {'demo_id'} or not body.demo_id:
            raise HTTPException(400, 'public mock requires demo_id only')
        demos_by_id = {d['id']: d for d in mock.DEMOS}
        demo = demos_by_id.get(body.demo_id)
        if demo is None:
            raise HTTPException(400, 'unknown fixed demo ID')
        try:
            job = agent.start(demo['prompt'], public_demo_id=demo['id'])
        except agent.JobCapacityError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {'id': job['id'], 'family': job['family'], 'inference_mode': 'MOCK'}
    text = (body.request or "").strip()
    if body.family == "counter" and not text:
        text = mock.DEMOS[0]["prompt"]
    if not text:
        raise HTTPException(400, "Describe a module first (or pick family=counter).")
    _ratelimit(request)
    job = agent.start(text)
    return {"id": job["id"], "family": job["family"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, since: int = 0):
    job = agent.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return {
        "id": job_id,
        "status": job["status"],
        "request": job["request"],
        "family": job["family"],
        "mock": job["mock"],
        "model": "mock" if job["mock"] else job["model"],
        "events": job["events"][since:],
        "next": len(job["events"]),
    }


@app.get("/api/jobs/{job_id}/wave.png")
def wave_png(job_id: str, attempt: int = 0):
    from . import vcd
    job = agent.JOBS.get(job_id)
    if not job or not job["attempts"]:
        raise HTTPException(404, "no waveform")
    a = job["attempts"][attempt - 1] if attempt else job["attempts"][-1]
    if not a.get("wave"):
        raise HTTPException(404, "attempt produced no VCD")
    status = "PASS" if a["result"].get("ok") else "FAIL"
    png = vcd.render_png(a["wave"], f"dut - attempt {a['attempt']} - {status}")
    return Response(png, media_type="image/png")


@app.post("/api/probe")
def probe(request: Request):
    if config.public_mock():
        raise HTTPException(404, 'not found')
    _ratelimit(request)
    if sandbox.USE_LOCAL:
        raise HTTPException(400, "Containment probe requires Docker sandbox (USE_LOCAL_SIM unset).")
    return sandbox.run_probe()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
