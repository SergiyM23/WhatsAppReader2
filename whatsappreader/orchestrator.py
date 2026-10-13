"""Single scheduled/manual pipeline, no independent AI worker."""
from __future__ import annotations
import fcntl
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from . import collector,gemini,reports,telegram,cleanup
from .logging_service import export_log,get_run_logger,recover_logs
from .settings import data_path
from .storage import Store

from .locks import AlreadyRunning,exclusive_lock


def retry_stage(name,attempts,delay,log,action):
    for attempt in range(1,attempts+1):
        try:return action()
        except Exception as exc:
            log.warning('%s attempt %d/%d failed: %s',name,attempt,attempts,exc)
            if attempt==attempts:raise
            time.sleep(delay)


def execute(trigger='scheduled',store=None,collector_fn=None,analyzer_fn=None):
    store=store or Store();store.initialize()
    with exclusive_lock():
        recover_logs(store)
        cfg=store.settings()  # Immutable snapshot for this run.
        run_id=store.start_run(trigger,cfg)
        log=get_run_logger(store,run_id)
        status='SUCCESS';error=None;stage='STARTING';report_path=None
        try:
            log.info('WhatsAppReader run #%d started (%s).',run_id,trigger)
            stage='WHATSAPP';store.stage(run_id,stage)
            log.info('Starting WhatsApp collection...')
            retry_stage('WhatsApp collection',cfg['collector_max_attempts'],cfg['retry_delay_seconds'],log,
                        lambda:(collector_fn or collector.collect)(store,run_id,cfg,log))
            stage='GEMINI';store.stage(run_id,stage)
            log.info('Starting Gemini analysis...')
            stats=(analyzer_fn or gemini.analyze_pending)(store,run_id,cfg,log)
            stage='REPORT';store.stage(run_id,stage)
            log.info('Generating report...')
            report_path=str(retry_stage('Report generation',cfg['report_max_attempts'],
                                        cfg['retry_delay_seconds'],log,lambda:reports.generate(store,run_id,cfg)))
            log.info('Generated report: %s',report_path)
            stage='TELEGRAM';store.stage(run_id,stage)
            log.info('Sending Telegram results notification...')
            try:telegram.send_results(cfg,stats,log)
            except Exception as exc:
                # A failed normal Telegram delivery should not invalidate processed results.
                log.error('Telegram result notification failed: %s',exc)
        except Exception as exc:
            status='FAILED';error=f'{stage}: {exc}'
            log.exception('Orchestrator failed in %s: %s',stage,exc)
            # Explicit error path: Error Handler -> Telegram -> Cleanup -> Finalize.
            telegram.send_failure(cfg,run_id,stage,exc,log)
        finally:
            store.stage(run_id,'CLEANUP')
            log.info('Starting cleanup...')
            try:cleanup.cleanup(store,cfg,log)
            except Exception as exc:
                log.exception('Cleanup failed: %s',exc)
                if status=='SUCCESS':status='FAILED';error=f'CLEANUP: {exc}'
                # One warning only; no recursion if Telegram is also unavailable.
                telegram.send_failure(cfg,run_id,'CLEANUP',exc,log)
            log.info('Run #%d finished with status %s.',run_id,status)
            store.finish_run(run_id,status,error,report_path)
            try:
                with store.connect() as db:
                    started_at=db.execute('SELECT started_at FROM runs WHERE id=?',(run_id,)).fetchone()[0]
                export_log(store,run_id,started_at)
            except Exception:
                log.exception('Could not export archived run log.')
        return status,run_id
