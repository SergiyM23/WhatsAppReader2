"""SQLite persistence and atomic checkpoint updates."""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .settings import DEFAULTS, data_path, validate


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (
 name TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings_history (
 id INTEGER PRIMARY KEY, updated_at TEXT NOT NULL, old_json TEXT NOT NULL,
 new_json TEXT NOT NULL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
 finished_at TEXT, status TEXT NOT NULL, stage TEXT, error TEXT,
 trigger TEXT NOT NULL, report_path TEXT, config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
 created_at TEXT NOT NULL, level TEXT NOT NULL, component TEXT NOT NULL, message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_logs_run ON logs(run_id,id);
CREATE TABLE IF NOT EXISTS messages (
 key TEXT PRIMARY KEY, chat TEXT NOT NULL, message_date TEXT, message_time TEXT,
 message_timestamp TEXT, author TEXT, direction TEXT, metadata TEXT,
 text TEXT NOT NULL, has_image INTEGER NOT NULL,
 image_path TEXT, image_attempts INTEGER NOT NULL DEFAULT 0,
 image_error TEXT, status TEXT NOT NULL DEFAULT 'PENDING_AI',
 discovered_at TEXT NOT NULL, discovered_run INTEGER
);
CREATE INDEX IF NOT EXISTS ix_messages_status ON messages(status,discovered_at);
CREATE TABLE IF NOT EXISTS analysis (
 message_key TEXT PRIMARY KEY, run_id INTEGER, status TEXT NOT NULL,
 score INTEGER, relevant INTEGER, reason TEXT, matched_aspects_json TEXT,
 model TEXT, interaction_id TEXT, error TEXT, analyzed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analysis_run ON analysis(run_id);
CREATE TABLE IF NOT EXISTS checkpoints (
 chat TEXT PRIMARY KEY, last_message_key TEXT NOT NULL,
 last_metadata TEXT, last_timestamp TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS housekeeping (
 name TEXT PRIMARY KEY, value TEXT NOT NULL
);
'''

class Store:
    def __init__(self,path:Path|None=None):
        self.path=Path(path or data_path('whatsappreader.db'))
        self.path.parent.mkdir(parents=True,exist_ok=True)

    @contextmanager
    def connect(self):
        con=sqlite3.connect(self.path,timeout=20)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=20000')
        con.execute('PRAGMA journal_mode=WAL')
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self):
        with self.connect() as db:
            db.executescript(SCHEMA)
            for key,val in DEFAULTS.items():
                db.execute('INSERT OR IGNORE INTO settings(name,value_json,updated_at) VALUES(?,?,?)',
                           (key,json.dumps(val,ensure_ascii=False),utcnow()))

    def settings(self):
        with self.connect() as db:
            rows=db.execute('SELECT name,value_json FROM settings').fetchall()
        return validate({r['name']:json.loads(r['value_json']) for r in rows})

    def save_settings(self,updates:dict,source='web'):
        previous=self.settings()
        new=validate({**previous,**updates})
        with self.connect() as db:
            now=utcnow()
            for key in updates:
                db.execute('INSERT INTO settings(name,value_json,updated_at) VALUES(?,?,?) '
                           'ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',
                           (key,json.dumps(new[key],ensure_ascii=False),now))
            db.execute('INSERT INTO settings_history(updated_at,old_json,new_json,source) VALUES(?,?,?,?)',
                       (now,json.dumps(previous,ensure_ascii=False),json.dumps(new,ensure_ascii=False),source))
        return new

    def start_run(self,trigger,config):
        with self.connect() as db:
            cur=db.execute('INSERT INTO runs(started_at,status,stage,trigger,config_json) VALUES(?,?,?,?,?)',
                           (utcnow(),'RUNNING','STARTING',trigger,json.dumps(config,ensure_ascii=False)))
            return cur.lastrowid

    def stage(self,run_id,name):
        with self.connect() as db:
            db.execute('UPDATE runs SET stage=? WHERE id=?',(name,run_id))

    def finish_run(self,run_id,status,error=None,report_path=None):
        with self.connect() as db:
            db.execute('UPDATE runs SET finished_at=?,status=?,stage=?,error=?,report_path=COALESCE(?,report_path) WHERE id=?',
                       (utcnow(),status,'DONE',error,report_path,run_id))

    def record_log(self,run_id,level,component,message):
        with self.connect() as db:
            db.execute('INSERT INTO logs(run_id,created_at,level,component,message) VALUES(?,?,?,?,?)',
                       (run_id,utcnow(),level,component,str(message)))

    def get_checkpoint(self,chat):
        with self.connect() as db:
            r=db.execute('SELECT * FROM checkpoints WHERE chat=?',(chat,)).fetchone()
        return dict(r) if r else None

    def save_scan(self,chat,messages,newest,run_id):
        """Persist messages before advancing checkpoint in the same transaction."""
        with self.connect() as db:
            for msg in messages:
                db.execute('''INSERT OR IGNORE INTO messages
                    (key,chat,message_date,message_time,message_timestamp,author,direction,metadata,
                     text,has_image,image_path,image_error,image_attempts,status,discovered_at,discovered_run)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (msg['key'],chat,msg.get('date'),msg.get('time'),msg.get('timestamp'),
                     msg.get('author'),msg.get('direction'),msg.get('metadata'),msg.get('text',''),
                     int(msg.get('hasImage',False)),msg.get('imagePath') or None,
                     msg.get('imageCaptureError') or None,msg.get('imageAttempts',0),
                     'PENDING_AI',utcnow(),run_id))
            db.execute('''INSERT INTO checkpoints(chat,last_message_key,last_metadata,last_timestamp,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(chat) DO UPDATE SET
                last_message_key=excluded.last_message_key,last_metadata=excluded.last_metadata,
                last_timestamp=excluded.last_timestamp,updated_at=excluded.updated_at''',
                (chat,newest['key'],newest['metadata'],newest.get('timestamp'),utcnow()))

    def update_image(self,key,path,error,attempts):
        with self.connect() as db:
            db.execute('UPDATE messages SET image_path=?,image_error=?,image_attempts=? WHERE key=?',
                       (str(path) if path else None,error,attempts,key))

    def pending(self):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM messages WHERE status='PENDING_AI' ORDER BY discovered_at,rowid")]

    def analyze(self,key,run_id,status,result=None,error=None):
        result=result or {}
        with self.connect() as db:
            db.execute('''INSERT INTO analysis
             (message_key,run_id,status,score,relevant,reason,matched_aspects_json,model,interaction_id,error,analyzed_at)
             VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(message_key) DO UPDATE SET
             run_id=excluded.run_id,status=excluded.status,score=excluded.score,relevant=excluded.relevant,
             reason=excluded.reason,matched_aspects_json=excluded.matched_aspects_json,
             model=excluded.model,interaction_id=excluded.interaction_id,error=excluded.error,
             analyzed_at=excluded.analyzed_at''',
              (key,run_id,status,result.get('score'),int(bool(result.get('relevant'))),
               result.get('reason'),json.dumps(result.get('matched_aspects',[]),ensure_ascii=False),
               result.get('model'),result.get('interaction_id'),error,utcnow()))
            db.execute('UPDATE messages SET status=? WHERE key=?',(status.upper(),key))

    def record_api_error(self,key,run_id,error):
        # Record a failed classification while leaving the message in PENDING_AI.
        with self.connect() as db:
            db.execute('INSERT INTO analysis(message_key,run_id,status,error,analyzed_at) '
                       'VALUES(?,?,?,?,?) ON CONFLICT(message_key) DO UPDATE SET '
                       'run_id=excluded.run_id,status=excluded.status,error=excluded.error, '
                       'analyzed_at=excluded.analyzed_at',
                       (key,run_id,'api_error',str(error),utcnow()))

    def running(self):
        with self.connect() as db:
            r=db.execute("SELECT * FROM runs WHERE status='RUNNING' ORDER BY id DESC LIMIT 1").fetchone()
        if not r:return None
        # A run killed by SIGKILL can leave a RUNNING row behind. The run lock
        # is the authoritative process-liveness check until startup recovery.
        import fcntl
        path=data_path('orchestrator.lock')
        if not path.exists():return None
        with path.open('a+') as fp:
            try:fcntl.flock(fp,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return dict(r)
            else:fcntl.flock(fp,fcntl.LOCK_UN)
        return None

    def recent_runs(self,limit=30):
        with self.connect() as db:
            return [dict(x) for x in db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT ?', (limit,))]

    def log_rows(self,run_id,after=0,limit=300):
        with self.connect() as db:
            return [dict(x) for x in db.execute('SELECT * FROM logs WHERE run_id=? AND id>? ORDER BY id LIMIT ?',
                                                 (run_id,after,limit))]

    def results(self,day=None,limit=300):
        sql='''SELECT m.*,a.status AS analysis_status,a.score,a.reason,a.matched_aspects_json,
               a.analyzed_at,a.error AS analysis_error FROM analysis a
               JOIN messages m ON m.key=a.message_key WHERE 1=1'''
        args=[]
        if day:
            sql+=' AND substr(a.analyzed_at,1,10)=?'; args.append(day)
        sql+=' ORDER BY a.analyzed_at DESC LIMIT ?'; args.append(limit)
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql,args)]
