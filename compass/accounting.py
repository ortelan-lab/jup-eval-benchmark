"""Durable local accounting. Unknown requests remain reserved; never replay them."""
import json
import math
import os
import sqlite3
import time
import threading
from pathlib import Path
from .core import require


def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class RequestJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.file = open(self.path, 'x', encoding='utf-8')
        os.chmod(self.path, 0o600)

    def append(self, event):
        with self.lock:
            self.file.write(json.dumps(dict(event, recorded_utc=stamp()), allow_nan=False) + '\n')
            self.file.flush()
            os.fsync(self.file.fileno())

    def close(self):
        self.file.close()


def audit_requests(path):
    requests = {}
    for line in Path(path).read_text().splitlines():
        event = json.loads(line)
        cid = event['call_id']
        if event['kind'] == 'reserved':
            require(cid not in requests, 'duplicate request reservation')
            amount = event['reserve_usd']
            require(type(amount) in (int, float) and math.isfinite(amount) and amount >= 0,
                    'invalid request reserve')
            requests[cid] = {'reserve': amount, 'settled': False, 'cost': None}
        elif event['kind'] == 'settled':
            require(cid in requests and not requests[cid]['settled'], 'invalid settlement')
            amount = event['cost_usd']
            require(type(amount) in (int, float) and math.isfinite(amount) and amount >= 0,
                    'invalid request cost')
            requests[cid].update(settled=True, cost=amount)
        else:
            require(event['kind'] == 'unknown' and cid in requests, 'invalid journal event')
    known = sum(r['cost'] for r in requests.values() if r['settled'])
    held = sum(r['reserve'] for r in requests.values() if not r['settled'])
    return {'requests': len(requests), 'known_cost_usd': known, 'held_usd': held,
            'conservative_exposure_usd': known + held,
            'unknown_requests': sum(not r['settled'] for r in requests.values()),
            'cost_basis': 'Configured token prices and provider-reported usage; not an invoice.'}


class StudyBudget:
    """One cumulative ceiling; increases require an explicit audited amendment."""
    def __init__(self, path, ceiling):
        require(type(ceiling) in (int, float) and math.isfinite(ceiling) and ceiling > 0,
                'positive study budget required')
        self.path = str(path)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, ceiling REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS allocations (run_id TEXT PRIMARY KEY, ceiling REAL NOT NULL, exposure REAL NOT NULL, state TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (ceiling,))
            require(db.execute('SELECT ceiling FROM settings WHERE id=1').fetchone()[0] == ceiling,
                    'study ceiling is frozen; do not silently change it')
        os.chmod(self.path, 0o600)

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def approve_increase(self, expected_ceiling, new_ceiling, approval_reference):
        """Operator-only, after the owner approves a new cumulative ceiling.

        Merely constructing a budget still cannot change its ceiling. Preserve
        all allocations and unknown charges and reject stale/repeated approval.
        """
        require(type(new_ceiling) in (int,float) and math.isfinite(new_ceiling)
                and new_ceiling > expected_ceiling, 'an increase is required')
        require(isinstance(approval_reference,str) and 12 <= len(approval_reference) <= 500,
                'explicit owner approval reference required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT ceiling FROM settings WHERE id=1').fetchone()[0]
            require(current == expected_ceiling, 'stale budget approval')
            db.execute('CREATE TABLE IF NOT EXISTS budget_amendments (approval_reference TEXT PRIMARY KEY, old_ceiling REAL NOT NULL, new_ceiling REAL NOT NULL, recorded_utc TEXT NOT NULL)')
            db.execute('INSERT INTO budget_amendments VALUES (?,?,?,?)',
                       (approval_reference,current,new_ceiling,stamp()))
            db.execute('UPDATE settings SET ceiling=? WHERE id=1',(new_ceiling,))

    def reserve(self, run_id, amount):
        require(type(amount) in (int, float) and math.isfinite(amount) and amount > 0,
                'positive run allocation required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            ceiling = db.execute('SELECT ceiling FROM settings').fetchone()[0]
            exposure = db.execute('SELECT COALESCE(SUM(exposure),0) FROM allocations').fetchone()[0]
            require(exposure + amount <= ceiling + 1e-10, 'study budget would be exceeded')
            db.execute('INSERT INTO allocations VALUES (?, ?, ?, ?)', (run_id, amount, amount, 'reserved'))

    def settle(self, run_id, audit):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM allocations WHERE run_id=?', (run_id,)).fetchone()
            require(row and row[0] == 'reserved', 'run not reserved or already settled')
            value = audit['conservative_exposure_usd']
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'invalid exposure')
            db.execute('UPDATE allocations SET exposure=?,state=? WHERE run_id=?',
                       (value, 'unknown' if audit['unknown_requests'] else 'settled', run_id))

    def summary(self):
        with self.db() as db:
            ceiling = db.execute('SELECT ceiling FROM settings').fetchone()[0]
            rows = db.execute('SELECT run_id,ceiling,exposure,state FROM allocations').fetchall()
        exposure = sum(r[2] for r in rows)
        return {'ceiling_usd': ceiling, 'exposure_usd': exposure,
                'available_usd': max(0, ceiling - exposure),
                'allocations': [dict(zip(('run_id', 'ceiling', 'exposure', 'state'), r)) for r in rows]}
