"""Configurable retention, protecting pending messages and active checkpoints."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .settings import data_path,logs_dir
from .storage import utcnow


def cleanup(store,cfg,logger,force=False):
    with store.connect() as db:
        row=db.execute("SELECT value FROM housekeeping WHERE name='last_cleanup'").fetchone()
    if row and not force:
        last=datetime.fromisoformat(row['value'])
        if datetime.now(timezone.utc)-last<timedelta(hours=cfg['cleanup_interval_hours']):
            logger.info('Cleanup not yet due.')
            return {}
    now=datetime.now(timezone.utc)
    cutoff=lambda name:(now-timedelta(days=cfg[name])).isoformat(timespec='seconds')
    counts={}
    with store.connect() as db:
        # Keep failed/pending jobs and all checkpoint rows. Analysis records may be retained
        # independently of message rows by preserving their referenced messages.
        cur=db.execute('DELETE FROM logs WHERE created_at<? AND run_id NOT IN '
                       "(SELECT id FROM runs WHERE status='RUNNING')",(cutoff('retention_logs_days'),))
        counts['logs']=cur.rowcount
        cur=db.execute('DELETE FROM analysis WHERE analyzed_at<?',(cutoff('retention_analysis_days'),))
        counts['analysis']=cur.rowcount
        cur=db.execute('DELETE FROM settings_history WHERE updated_at<?',
                       (cutoff('retention_settings_history_days'),))
        counts['settings_history']=cur.rowcount
        candidates=db.execute('''SELECT key,image_path FROM messages WHERE discovered_at<?
            AND status NOT IN ('PENDING_AI','API_ERROR')
            AND key NOT IN (SELECT last_message_key FROM checkpoints)
            AND key NOT IN (SELECT message_key FROM analysis)''',
            (cutoff('retention_messages_days'),)).fetchall()
        keys=[r['key'] for r in candidates]
        if keys:
            db.executemany('DELETE FROM messages WHERE key=?',[(key,) for key in keys])
        counts['messages']=len(keys)
        cur=db.execute('DELETE FROM runs WHERE started_at<? AND status!=\'RUNNING\' '
                       'AND id NOT IN (SELECT run_id FROM analysis WHERE run_id IS NOT NULL) '
                       'AND id NOT IN (SELECT DISTINCT run_id FROM logs)',
                       (cutoff('retention_runs_days'),))
        counts['runs']=cur.rowcount
        db.execute('INSERT INTO housekeeping(name,value) VALUES(?,?) '
                   'ON CONFLICT(name) DO UPDATE SET value=excluded.value',('last_cleanup',utcnow()))
        pending_images={str(r[0]) for r in db.execute("SELECT image_path FROM messages WHERE image_path IS NOT NULL AND status='PENDING_AI'")}
    for folder,setting,suffix in [('logs','retention_log_files_days','.log'),
                                  ('reports','retention_reports_days','.html'),
                                  ('images','retention_images_days','.png')]:
        deleted=0;threshold=(now-timedelta(days=cfg[setting])).timestamp()
        directory=logs_dir() if folder=='logs' else data_path(folder)
        if directory.exists():
            for p in directory.glob('*'+suffix):
                try:
                    if p.stat().st_mtime>=threshold:continue
                    if folder=='images' and str(p) in pending_images:continue
                    p.unlink();deleted+=1
                    if folder=='images':
                        with store.connect() as db:
                            db.execute("UPDATE messages SET image_path=NULL WHERE image_path=? AND status!='PENDING_AI'",(str(p),))
                    elif folder=='reports':
                        with store.connect() as db:
                            db.execute('UPDATE runs SET report_path=NULL WHERE report_path=?',(str(p),))
                except OSError as exc:logger.warning('Could not remove %s: %s',p,exc)
        counts[folder+'_files']=deleted
    aux=data_path('qr-session.log')
    if aux.exists() and aux.stat().st_mtime<(now-timedelta(days=cfg['retention_log_files_days'])).timestamp():
        try:aux.unlink();counts['qr_session_logs']=1
        except OSError as exc:logger.warning('Could not remove %s: %s',aux,exc)
    logger.info('Cleanup complete: %s',counts)
    return counts
