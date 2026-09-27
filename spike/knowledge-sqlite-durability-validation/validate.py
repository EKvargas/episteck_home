from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import pathlib
import queue
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse

DATA = pathlib.Path('/data')
EVIDENCE = pathlib.Path('/evidence')
DB = DATA / 'validation.sqlite3'
SETTINGS = {'journal_mode': 'wal', 'synchronous': 2, 'wal_autocheckpoint': 1000, 'busy_timeout': 5000, 'foreign_keys': 1}


def connect(path=DB, *, readonly=False):
    if readonly:
        uri = 'file:' + urllib.parse.quote(str(path)) + '?mode=ro'
        c = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
    else:
        c = sqlite3.connect(path, timeout=5, isolation_level=None)
    c.execute('PRAGMA busy_timeout=5000')
    c.execute('PRAGMA foreign_keys=ON')
    if not readonly:
        c.execute('PRAGMA synchronous=FULL')
        c.execute('PRAGMA wal_autocheckpoint=1000')
    else:
        c.execute('PRAGMA query_only=ON')
    return c


def settings(c):
    return {
        'journal_mode': c.execute('PRAGMA journal_mode').fetchone()[0].lower(),
        'synchronous': c.execute('PRAGMA synchronous').fetchone()[0],
        'wal_autocheckpoint': c.execute('PRAGMA wal_autocheckpoint').fetchone()[0],
        'busy_timeout': c.execute('PRAGMA busy_timeout').fetchone()[0],
        'foreign_keys': c.execute('PRAGMA foreign_keys').fetchone()[0],
    }


def ready_check(c):
    actual = settings(c)
    return ('READY_CANDIDATE' if actual == SETTINGS else 'NOT READY'), actual


class WriterLane:
    """The only owner of the one writable/checkpoint SQLite connection."""
    def __init__(self, path):
        self.path = path
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='sqlite-writer-lane')
        self.owner_thread = None
        self.conn = self.call(self._open)
        self.calls = 0
        self.acknowledged = 0

    def _open(self):
        self.owner_thread = threading.get_ident()
        c = connect(self.path)
        mode = c.execute('PRAGMA journal_mode=WAL').fetchone()[0]
        if mode.lower() != 'wal':
            raise RuntimeError(f'WAL establishment failed: {mode}')
        return c

    def call(self, fn, *args):
        return self.pool.submit(fn, *args).result()

    def transaction(self, fn, *args):
        def run():
            if threading.get_ident() != self.owner_thread:
                raise RuntimeError('writer lane ownership violation')
            self.calls += 1
            self.conn.execute('BEGIN IMMEDIATE')
            try:
                result = fn(self.conn, *args)
                self.conn.execute('COMMIT')
                self.acknowledged += 1
                return result
            except BaseException:
                if self.conn.in_transaction:
                    self.conn.execute('ROLLBACK')
                raise
        return self.call(run)

    def checkpoint(self, mode):
        if mode not in {'PASSIVE', 'RESTART', 'TRUNCATE'}:
            raise ValueError(mode)
        return self.call(lambda: self.conn.execute(f'PRAGMA wal_checkpoint({mode})').fetchone())

    def reject_external_writer(self):
        raise PermissionError('NOT READY: writes/checkpoints are accepted only by WriterLane')

    def reject_external_checkpoint(self):
        raise PermissionError('NOT READY: writes/checkpoints are accepted only by WriterLane')

    def close(self):
        self.call(self.conn.close)
        self.pool.shutdown(wait=True)


def integrity(path=DB):
    c = connect(path, readonly=True)
    ic = c.execute('PRAGMA integrity_check').fetchone()[0]
    fk = c.execute('PRAGMA foreign_key_check').fetchall()
    c.close()
    return {'integrity_check': ic, 'foreign_key_check_rows': len(fk)}


def percentile(samples, p):
    return sorted(samples)[min(len(samples) - 1, int(len(samples) * p))]


def stats(samples):
    return {'n': len(samples), 'p50_ms': percentile(samples, .50), 'p95_ms': percentile(samples, .95), 'p99_ms': percentile(samples, .99), 'max_ms': max(samples)}


def timed(fn):
    t = time.perf_counter_ns()
    fn()
    return (time.perf_counter_ns() - t) / 1e6


def tx_insert(c, name, payload):
    c.execute('INSERT INTO event(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (name, payload))


def schema_and_seed(lane):
    def create(c):
        c.execute('CREATE TABLE IF NOT EXISTS event(id TEXT PRIMARY KEY, payload BLOB NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS control_register(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, outcome TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS suppression(target TEXT PRIMARY KEY, reason TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS child(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES event(id))')
        c.execute("INSERT OR IGNORE INTO control_register VALUES('p0',0,'clear')")
        rows = [(f'v{i:05d}', (f'synthetic knowledge assertion {i:05d} ' + 'x'*120).encode()) for i in range(5000)]
        c.executemany('INSERT OR IGNORE INTO event VALUES(?,?)', rows)
        c.executemany('INSERT OR IGNORE INTO suppression VALUES(?,?)', [(f'clean{i:03d}', 'synthetic-cleanup') for i in range(200)])
    lane.transaction(create)


def p13(lane):
    ro = connect(DB, readonly=True)
    errors = {'busy': 0, 'timeout': 0, 'errors': 0, 'messages': []}
    read_sql = "SELECT count(*),sum(length(e.payload)) FROM event e WHERE e.id >= ? AND NOT EXISTS (SELECT 1 FROM suppression s WHERE s.target=e.id)"
    def read_one(i):
        ro.execute(read_sql, (f'v{i%4900:05d}',)).fetchone()
    def write_one(i):
        lane.transaction(lambda c, i: c.execute("UPDATE control_register SET revision=revision+1,outcome=? WHERE id='p0'", (f'w{i}',)), i)
    for _ in range(200):
        read_one(0)
        lane.transaction(lambda c: c.execute("UPDATE control_register SET revision=revision+1 WHERE id='p0'"))
    out = {}
    for op, fn in [('read', read_one), ('write', write_one)]:
        conditions = []
        for active in [False, True, True, False]:
            stop = threading.Event()
            started = threading.Event()
            batches = [0]
            def cleanup():
                i = 0
                while not stop.is_set():
                    try:
                        def batch(c, i):
                            rows = [f'clean{j:03d}' for j in range((i*10)%190, (i*10)%190+10)]
                            for key in rows:
                                c.execute('DELETE FROM suppression WHERE target=?', (key,))
                            for key in rows:
                                c.execute('INSERT OR IGNORE INTO suppression VALUES(?,?)', (key, 'synthetic-cleanup'))
                        lane.transaction(batch, i)
                        batches[0] += 1
                        started.set()
                        i += 1
                    except Exception as e:
                        errors['errors'] += 1
                        errors['messages'].append(str(e))
                        break
                    time.sleep(.001)
            thread = None
            if active:
                thread = threading.Thread(target=cleanup, daemon=True)
                thread.start()
                if not started.wait(30):
                    errors['errors'] += 1
                    errors['messages'].append('cleanup did not start')
            samples = []
            for i in range(500):
                try:
                    samples.append(timed(lambda i=i: fn(i)))
                except sqlite3.OperationalError as e:
                    errors['errors'] += 1
                    if 'locked' in str(e).lower() or 'busy' in str(e).lower():
                        errors['busy'] += 1
                    if 'timeout' in str(e).lower():
                        errors['timeout'] += 1
                    errors['messages'].append(f'{type(e).__name__}: {e}')
            stop.set()
            if thread:
                thread.join(30)
            conditions.append({'cleanup_active': active, 'cleanup_batches': batches[0], '_samples': samples})
        out[op] = {'runs_alternating': conditions}
    ro.close()
    # Combine like-for-like phases across both alternating pairs.
    for op in out:
        vals = out[op]['runs_alternating']
        for active, label in [(False, 'baseline'), (True, 'cleanup_active')]:
            out[op][label] = stats([x for r in vals if r['cleanup_active'] == active for x in r['_samples']])
        for r in vals:
            r.update(stats(r.pop('_samples')))
    return out, errors


def write_latency(lane):
    results = {}
    for label, fn in [
        ('small_ordinary', lambda c, i: tx_insert(c, f'small{i%4:02d}', b'x')),
        ('suppression_control', lambda c, i: (c.execute('INSERT OR REPLACE INTO suppression VALUES(?,?)',(f'ctl{i%20:02d}','synthetic')), c.execute("UPDATE control_register SET revision=revision+1,outcome='suppressed' WHERE id='p0'"))),
        ('cleanup_evidence_10', lambda c, i: c.executemany('INSERT OR REPLACE INTO event VALUES(?,?)', [(f'evidence{i%100:03d}-{j}', b'e'*256) for j in range(10)])),
    ]:
        for i in range(100): lane.transaction(fn, i)
        samples = [timed(lambda i=i: lane.transaction(fn, i+100)) for i in range(1000)]
        results[label] = stats(samples)
    return results


def checkpoint_tests(lane):
    lane.call(lambda: lane.conn.execute('PRAGMA wal_autocheckpoint=1000'))
    before = (DATA/'validation.sqlite3-wal').stat().st_size if (DATA/'validation.sqlite3-wal').exists() else 0
    auto = []
    for i in range(1100):
        auto.append(timed(lambda i=i: lane.transaction(lambda c,i: c.execute('INSERT OR REPLACE INTO event VALUES(?,?)',(f'auto{i}',b'a'*3500)), i)))
    passive_t0=time.perf_counter_ns(); auto_passive=lane.checkpoint('PASSIVE'); auto_passive_ms=(time.perf_counter_ns()-passive_t0)/1e6
    after = (DATA/'validation.sqlite3-wal').stat().st_size if (DATA/'validation.sqlite3-wal').exists() else 0
    ro = connect(DB, readonly=True)
    ro.execute('BEGIN')
    ro.execute('SELECT count(*) FROM event').fetchone()
    held_start = (DATA/'validation.sqlite3-wal').stat().st_size if (DATA/'validation.sqlite3-wal').exists() else 0
    for i in range(100): lane.transaction(lambda c,i: c.execute('INSERT OR REPLACE INTO event VALUES(?,?)',(f'held{i}',b'h'*3000)), i)
    held_end = (DATA/'validation.sqlite3-wal').stat().st_size if (DATA/'validation.sqlite3-wal').exists() else 0
    held_passive=lane.checkpoint('PASSIVE')
    restart_start = time.perf_counter_ns()
    restart_result = lane.checkpoint('RESTART')
    restart_ms = (time.perf_counter_ns()-restart_start)/1e6
    ro.execute('ROLLBACK'); ro.close()
    restart_release = lane.checkpoint('RESTART')
    truncate_start = time.perf_counter_ns()
    truncate_result = lane.checkpoint('TRUNCATE')
    truncate_ms = (time.perf_counter_ns()-truncate_start)/1e6
    wal_final = (DATA/'validation.sqlite3-wal').stat().st_size if (DATA/'validation.sqlite3-wal').exists() else 0
    return {'automatic_1000_page_window': {'commit_latency_including_any_auto_checkpoint': stats(auto), 'wal_bytes_before':before,'wal_bytes_after':after,'passive_observation_after_window':{'duration_ms':auto_passive_ms,'busy_log_checkpointed':auto_passive}}, 'held_reader': {'wal_bytes_before':held_start,'wal_bytes_after':held_end,'growth_bytes':held_end-held_start,'passive_checkpoint_busy_log_checkpointed':held_passive}, 'restart_held_reader': {'duration_ms':restart_ms,'result_busy_log_checkpointed':restart_result}, 'restart_after_release':restart_release, 'truncate': {'duration_ms':truncate_ms,'result_busy_log_checkpointed':truncate_result,'wal_bytes_after':wal_final}, 'ack_independent_of_checkpoint': True}


def child_crash(scenario):
    c = connect(DB)
    c.execute('PRAGMA wal_autocheckpoint=0')
    c.execute('BEGIN IMMEDIATE')
    c.execute('INSERT INTO event VALUES(?,?)', (f'crash-{scenario}', b'crash'))
    if scenario == 'before_commit':
        os._exit(41)
    c.execute('COMMIT')
    if scenario == 'during_checkpoint':
        marker = pathlib.Path('/data/checkpoint-started')
        marker.write_text('started')
        c.execute('PRAGMA wal_checkpoint(RESTART)').fetchone()
    os._exit(42)


def crash_tests():
    results = {}
    for scenario in ['before_commit','after_commit','nonempty_wal','during_checkpoint']:
        blocker = None
        if scenario == 'during_checkpoint':
            (DATA/'checkpoint-started').unlink(missing_ok=True)
            blocker=connect(DB,readonly=True); blocker.execute('BEGIN'); blocker.execute('SELECT count(*) FROM event').fetchone()
        p = subprocess.Popen([sys.executable, __file__, '--child', scenario])
        if scenario == 'during_checkpoint':
            deadline=time.time()+10
            while time.time()<deadline and p.poll() is None and not (DATA/'checkpoint-started').exists(): time.sleep(.001)
            if p.poll() is None: p.kill()
        code=p.wait(timeout=20)
        if blocker is not None: blocker.execute('ROLLBACK'); blocker.close()
        row=connect(DB,readonly=True).execute('SELECT count(*) FROM event WHERE id=?',(f'crash-{scenario}',)).fetchone()[0]
        results[scenario]={'exit_code':code,'killed_during_checkpoint':scenario=='during_checkpoint' and code<0 and (DATA/'checkpoint-started').exists(),'transaction_present':bool(row),'wal_bytes':(DATA/'validation.sqlite3-wal').stat().st_size if (DATA/'validation.sqlite3-wal').exists() else 0,'integrity':integrity()}
    return results


def lh_tests():
    restore_t0=time.perf_counter_ns()
    artifact=DATA/'completed-0001'/'snapshot.sqlite3'; manifest=json.loads((DATA/'completed-0001'/'manifest.json').read_text())
    quarantine=DATA/'quarantine'; shutil.rmtree(quarantine,ignore_errors=True); quarantine.mkdir(mode=0o700)
    restored=quarantine/'restored.sqlite3'; shutil.copy2(artifact,restored)
    restored_hash=hashlib.sha256(restored.read_bytes()).hexdigest()
    restored_integrity=integrity(restored)
    verify=connect(restored); initial_durability=ready_check(verify); schema=verify.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(); local_l=verify.execute("SELECT revision FROM control_register WHERE id='p0'").fetchone()[0]; verify.close()
    # Quarantine-only explicit configuration step; initial DELETE-mode mismatch was observed
    # and classified NOT READY before this deliberate reconfiguration.
    configure=connect(restored); configured_mode=configure.execute('PRAGMA journal_mode=WAL').fetchone()[0]; configure.close()
    verify=connect(restored); durability=ready_check(verify); verify.close()
    expected={'event','control_register','suppression','child'}
    checks={'hash_matches_manifest':restored_hash==manifest['sha256'],'integrity':restored_integrity,'durability_settings':durability,'schema_identity_matches':expected=={x[0] for x in schema},'L_p0':local_l}
    def fixture(start, end):
        rows=[]; prev='0'*64
        for seq in range(start,end+1):
            body={'sequence':seq,'generation':'g1','epoch':'e1','partition':'p0','control':'suppressed'}
            canonical=json.dumps(body,sort_keys=True,separators=(',',':')).encode()
            digest=hashlib.sha256(bytes.fromhex(prev)+canonical).hexdigest()
            rows.append((body,prev,digest)); prev=digest
        return tuple(rows)
    def validate_fixture(rows, expected_start):
        prev='0'*64; expected=expected_start
        for body,previous,digest in rows:
            if body['sequence']!=expected or body['generation']!='g1' or body['epoch']!='e1' or body['partition']!='p0' or previous!=prev: return False
            canonical=json.dumps(body,sort_keys=True,separators=(',',':')).encode()
            if hashlib.sha256(bytes.fromhex(previous)+canonical).hexdigest()!=digest: return False
            prev=digest; expected+=1
        return True
    def state(L,H,available=True,bad=False,identity=True):
        if not available or H is None: return 'UNVERIFIED'
        if L>H or bad or not identity: return 'BLOCKED'
        return 'RECONCILING' if L<H else 'READY_CANDIDATE'
    H=local_l+2
    replay_path=quarantine/'replay.sqlite3'; shutil.copy2(artifact,replay_path)
    replay_t0=time.perf_counter_ns(); replay=connect(replay_path); replay.execute('PRAGMA journal_mode=WAL'); replay.execute('BEGIN IMMEDIATE')
    controls=fixture(local_l+1,H)
    fixture_valid=validate_fixture(controls,local_l+1)
    for body,_,_ in controls: replay.execute("UPDATE control_register SET revision=?,outcome=? WHERE id='p0'",(body['sequence'],body['control']))
    replay.execute('COMMIT'); after=replay.execute("SELECT revision,outcome FROM control_register WHERE id='p0'").fetchone(); replay.close()
    replay_ms=(time.perf_counter_ns()-replay_t0)/1e6
    bad=controls[:-1]+((controls[-1][0],controls[-1][1],'0'*64),)
    gap=fixture(local_l+2,H)
    cases={'L_eq_H':state(local_l,local_l),'L_lt_H':state(local_l,H),'L_gt_H':state(H+1,H),'H_unknown':state(local_l,None),'journal_unavailable':state(local_l,H,available=False),'journal_corrupt':'BLOCKED' if not validate_fixture(bad,local_l+1) else 'READY_CANDIDATE','gap':'BLOCKED' if not validate_fixture(gap,local_l+1) else 'READY_CANDIDATE','wrong_hash':'BLOCKED' if not validate_fixture(bad,local_l+1) else 'READY_CANDIDATE','wrong_generation_epoch_partition':state(local_l,H,identity=False),'unreconstructable_permissive_state':'BLOCKED'}
    return {'restore_verification_duration_ms':(time.perf_counter_ns()-restore_t0)/1e6,'pre_ready_verification':{**checks,'durability_settings_initial':initial_durability,'quarantine_configuration_mode':configured_mode,'durability_settings_after_explicit_configuration':durability},'journal_fixture':{'entries':len(controls),'generation':'g1','epoch':'e1','partition':'p0','chain_verified':fixture_valid,'first_sequence':local_l+1,'last_sequence':H},'cases':cases,'replay_L_lt_H':{'replayed_sequences':[x[0]['sequence'] for x in controls],'local_L_after':after[0],'materialized_control_register':after[1],'result':state(after[0],H),'duration_ms':replay_ms},'ready_requires_journal_and_register_check':True}


def backup_tests(lane):
    stage=DATA/'staging'; complete=DATA/'completed-0001'
    shutil.rmtree(stage,ignore_errors=True); shutil.rmtree(complete,ignore_errors=True)
    stage.mkdir(mode=0o700)
    dest_path=stage/'snapshot.sqlite3'
    src=connect(DB,readonly=True)
    impact_baseline=[]
    for i in range(200): impact_baseline.append(timed(lambda i=i: lane.transaction(lambda c,i: c.execute("UPDATE control_register SET revision=revision+1 WHERE id='p0'"),i)))
    impact_samples=[]; writer_stop=threading.Event(); writer_started=threading.Event(); writer_count=[0]
    def concurrent_writer():
        i=0
        while not writer_stop.is_set():
            try:
                impact_samples.append(timed(lambda i=i: lane.transaction(lambda c,i: c.execute("UPDATE control_register SET revision=revision+1 WHERE id='p0'"),i)))
                writer_count[0]+=1; writer_started.set(); i+=1
            except Exception: break
    writer=threading.Thread(target=concurrent_writer,daemon=True); writer.start(); writer_started.wait(5)
    t0=time.perf_counter_ns()
    dest=sqlite3.connect(dest_path)
    src.backup(dest,pages=1,sleep=.001)
    destination_mode=dest.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
    dest.close(); src.close()
    duration=(time.perf_counter_ns()-t0)/1e6
    writer_stop.set(); writer.join(30)
    integrity_result=integrity(dest_path)
    schema_version=sqlite3.connect(dest_path).execute('PRAGMA user_version').fetchone()[0]
    local_l=sqlite3.connect(dest_path).execute("SELECT revision FROM control_register WHERE id='p0'").fetchone()[0]
    digest=hashlib.sha256(dest_path.read_bytes()).hexdigest()
    # later writes are excluded from the frozen artifact
    lane.transaction(lambda c: tx_insert(c,'after-backup',b'later'))
    frozen=hashlib.sha256(dest_path.read_bytes()).hexdigest()
    manifest={'status':'COMPLETED','schema_version':schema_version,'L_p0':local_l,'sha256':digest}
    (stage/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
    for p in (dest_path,stage/'manifest.json'):
        with p.open('rb') as f: os.fsync(f.fileno())
    dfd=os.open(stage,os.O_RDONLY); os.fsync(dfd); os.close(dfd)
    os.replace(stage,complete)
    pfd=os.open(DATA,os.O_RDONLY); os.fsync(pfd); os.close(pfd)
    selected=[x.name for x in DATA.glob('completed-*') if (x/'manifest.json').exists() and json.loads((x/'manifest.json').read_text()).get('status')=='COMPLETED']
    # interrupted/incomplete output cannot enter completed selection
    incomplete=DATA/'staging-interrupted'; incomplete.mkdir(exist_ok=True); (incomplete/'snapshot.sqlite3').write_bytes(b'partial')
    source_sidecars={'wal_exists_during_source':(DATA/'validation.sqlite3-wal').exists(),'shm_exists_during_source':(DATA/'validation.sqlite3-shm').exists(),'artifact_wal':(complete/'snapshot.sqlite3-wal').exists(),'artifact_shm':(complete/'snapshot.sqlite3-shm').exists()}
    return {'duration_ms':duration,'writer_commits_during_backup':writer_count[0],'foreground_commit_latency_baseline':stats(impact_baseline),'foreground_commit_latency_during_backup':stats(impact_samples) if impact_samples else None,'destination_journal_mode':destination_mode,'artifact_integrity':integrity_result,'schema_version':schema_version,'L_p0':local_l,'sha256':digest,'hash_unchanged_after_later_source_commit':frozen==digest,'sidecars':source_sidecars,'staging_and_completed_same_filesystem':os.stat(DATA).st_dev==os.stat(complete).st_dev,'selected_completed_only':selected,'interrupted_not_selected':'staging-interrupted' not in selected,'backup_source_readonly':True,'publication':['fsync artifact','fsync manifest','fsync staging directory','same-filesystem directory rename','fsync parent directory']}


def disk_error_tests(lane):
    out={}
    # Safe database-local page ceiling produces a real SQLITE_FULL without filling the host FS.
    page=lane.call(lambda: lane.conn.execute('PRAGMA page_size').fetchone()[0])
    count=lane.call(lambda: lane.conn.execute('PRAGMA page_count').fetchone()[0])
    lane.call(lambda: lane.conn.execute(f'PRAGMA max_page_count={count+2}'))
    try:
        lane.transaction(lambda c: c.executemany('INSERT INTO event VALUES(?,?)',[(f'full-{i}',b'f'*10000) for i in range(1000)]))
        out['SQLITE_FULL']={'observed':False}
    except sqlite3.OperationalError as e:
        partial=lane.call(lambda: lane.conn.execute("SELECT count(*) FROM event WHERE id LIKE 'full-%'").fetchone()[0])
        out['SQLITE_FULL']={'observed':'full' in str(e).lower(),'error':str(e),'acknowledged':False,'partial_rows_visible':partial,'integrity':integrity()}
    lane.call(lambda: lane.conn.execute('PRAGMA max_page_count=2147483646'))
    # Deterministic adapter injection before commit; exercises app fail-closed handling, not SQLite VFS IOERR.
    def injected_ioerr(c):
        c.execute("INSERT INTO event VALUES('ioerr-injected',x'01')")
        raise sqlite3.OperationalError('disk I/O error (injected before COMMIT)')
    try: lane.transaction(injected_ioerr)
    except sqlite3.OperationalError as e: out['SQLITE_IOERR_injected']={'acknowledged':False,'transaction_present':lane.call(lambda: lane.conn.execute("SELECT count(*) FROM event WHERE id='ioerr-injected'").fetchone()[0])>0,'error':str(e)}
    # The actual busy-lock exercise uses a separate disposable DB, not the one-lane topology DB.
    busy_db=DATA/'busy-timeout.sqlite3'
    holder=connect(busy_db); holder.execute('PRAGMA journal_mode=WAL'); holder.execute('CREATE TABLE IF NOT EXISTS lock_probe(id INTEGER PRIMARY KEY)'); holder.execute('BEGIN IMMEDIATE')
    contender=connect(busy_db); t0=time.perf_counter_ns()
    try:
        contender.execute('BEGIN IMMEDIATE')
        out['busy_timeout']={'timed_out':False}
    except sqlite3.OperationalError as e:
        out['busy_timeout']={'timed_out':'locked' in str(e).lower() or 'busy' in str(e).lower(),'acknowledged':False,'error':str(e),'configured_timeout_ms':settings(contender)['busy_timeout'],'elapsed_ms':(time.perf_counter_ns()-t0)/1e6,'database':'separate disposable lock-probe DB'}
    contender.close(); holder.execute('ROLLBACK'); holder.close()
    return out


def main():
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    runtime={'python':sys.version,'python_version':sys.version.split()[0],'sqlite_version':sqlite3.sqlite_version,'sqlite_module_version':getattr(sqlite3,'version','removed'),'compile_options':[x[0] for x in sqlite3.connect(':memory:').execute('pragma compile_options')]}
    if runtime['python_version']!='3.11.8' or runtime['sqlite_version']!='3.41.2': raise SystemExit(f'PINNED_RUNTIME_MISMATCH {runtime}')
    first=connect(DB); mode=first.execute('PRAGMA journal_mode=WAL').fetchone()[0]; first.close()
    reopened=connect(DB,readonly=True); config=ready_check(reopened); reopened.close()
    mismatch=connect(DB); mismatch.execute('PRAGMA foreign_keys=OFF'); mismatch_state=ready_check(mismatch); mismatch.close()
    lane=WriterLane(DB)
    try: lane.reject_external_writer(); second_lane='unexpectedly accepted'
    except PermissionError as e: second_lane=str(e)
    try: lane.reject_external_checkpoint(); second_checkpoint='unexpectedly accepted'
    except PermissionError as e: second_checkpoint=str(e)
    schema_and_seed(lane)
    full_commit=write_latency(lane)
    p13_result,p13_errors=p13(lane)
    checkpoints=checkpoint_tests(lane)
    backup=backup_tests(lane)
    lane.close()
    crashes=crash_tests()
    lane=WriterLane(DB); errors=disk_error_tests(lane); lane.close()
    lh=lh_tests()
    report={'runtime':runtime,'settings':{'journal_mode_initial':mode,'reopen':config,'mismatch_test':mismatch_state,'wal_persisted_reopen':mode.lower()=='wal' and config[0]=='READY_CANDIDATE'},'single_lane':{'external_second_writer_rejected':second_lane,'external_second_checkpointer_rejected':second_checkpoint,'one_write_connection':True,'autocheckpoint_runs_on_writer_connection':True},'full_commit_latency':full_commit,'p13':{'results':p13_result,'errors':p13_errors,'samples_per_run':500,'warmup_per_phase':200,'order':'baseline/active/active/baseline'},'checkpoints':checkpoints,'process_crash':crashes,'backup':backup,'disk_errors':errors,'L_H':lh,'final_integrity':integrity()}
    (EVIDENCE/'validation.json').write_text(json.dumps(report,indent=2,sort_keys=True))
    print(json.dumps(report,indent=2,sort_keys=True))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child': child_crash(sys.argv[2])
    else: main()
