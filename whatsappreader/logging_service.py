"""Persist run logs immediately, archive on completion, and support live UI access."""
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
from pathlib import Path
from .settings import logs_dir

class DatabaseLogHandler(logging.Handler):
    def __init__(self,store,run_id):
        super().__init__()
        self.store=store
        self.run_id=run_id

    def emit(self,record):
        try:
            message=record.getMessage()
            if record.exc_info:
                message+='\n'+logging.Formatter().formatException(record.exc_info)
            self.store.record_log(self.run_id,record.levelname,record.name,message)
        except Exception:
            self.handleError(record)


def get_run_logger(store,run_id):
    logger=logging.getLogger(f'whatsappreader.run.{run_id}')
    logger.setLevel(logging.INFO)
    logger.propagate=False
    for old_handler in list(logger.handlers):
        logger.removeHandler(old_handler)
        old_handler.close()
    logger.addHandler(DatabaseLogHandler(store,run_id))
    stream=logging.StreamHandler()
    stream.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(stream)
    return logger


def export_log(store,run_id,started_at):
    timestamp=datetime.fromisoformat(started_at).astimezone(ZoneInfo('Europe/Madrid'))
    directory=logs_dir()
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/('run_'+timestamp.strftime('%Y-%m-%d_%H%M%S')+'.log')
    temporary=target.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as fp:
        last=0
        while True:
            rows=store.log_rows(run_id,last,500)
            for r in rows:
                fp.write(f"{r['created_at']} [{r['level']}] [{r['component']}] {r['message']}\n")
                last=r['id']
            if len(rows)<500:break
    temporary.replace(target)
    return target


def recover_logs(store):
    with store.connect() as db:
        stale=[dict(row) for row in db.execute("SELECT * FROM runs WHERE status='RUNNING'")]
    # Called only by a process holding the exclusive run lock.
    for run in stale:
        store.record_log(run['id'],'ERROR','recovery','Previous process terminated without finalization.')
        store.finish_run(run['id'],'FAILED','Process terminated unexpectedly.')
        export_log(store,run['id'],run['started_at'])
