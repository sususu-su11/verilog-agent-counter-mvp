"""Durable, fail-closed request counter. Charges each attempt BEFORE network I/O.

This is NOT a financial guarantee or a Vultr account-level spending cap.
The DB persists across restarts; the configured allowance cannot be silently reset.
"""
from __future__ import annotations
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def consume_one() -> int:
    path = os.environ.get('INFERENCE_LEDGER_PATH', '').strip()
    limit = int(os.environ.get('LIVE_INFERENCE_MAX_CALLS', '0'))
    if not path or limit < 1:
        raise RuntimeError('LIVE_INFERENCE_BUDGET_NOT_CONFIGURED')
    if not Path(path).parent.is_dir():
        raise RuntimeError('LIVE_INFERENCE_LEDGER_DIR_MISSING')
    with closing(sqlite3.connect(path, timeout=5, isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS quota (id INTEGER PRIMARY KEY CHECK (id=1), used INTEGER NOT NULL, max_calls INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO quota(id,used,max_calls) VALUES(1,0,?)', (limit,))
        used, stored_limit = db.execute('SELECT used,max_calls FROM quota WHERE id=1').fetchone()
        if limit != stored_limit:
            db.execute('ROLLBACK')
            raise RuntimeError('LIVE_INFERENCE_BUDGET_CHANGE_REQUIRES_MANUAL_REVIEW')
        if used >= limit:
            db.execute('ROLLBACK')
            raise RuntimeError('LIVE_INFERENCE_BUDGET_EXHAUSTED')
        db.execute('UPDATE quota SET used=used+1 WHERE id=1')
        db.execute('COMMIT')
        return limit - used - 1
