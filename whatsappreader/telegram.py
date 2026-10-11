"""English Telegram notifications, with bounded retries and no error recursion."""
import os
import time
import httpx


def send(text,cfg,logger):
    token=os.getenv('TELEGRAM_BOT_TOKEN','')
    chat=cfg.get('telegram_chat_id','').strip()
    if not token or not chat:raise RuntimeError('Telegram bot token or chat ID is not configured.')
    for attempt in range(1,cfg['telegram_max_attempts']+1):
        try:
            with httpx.Client(timeout=20) as client:
                response=client.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                     json={'chat_id':chat,'text':text})
                response.raise_for_status()
                payload=response.json()
                if payload.get('ok') is not True:raise RuntimeError('Telegram did not acknowledge message.')
                return True
        except Exception as exc:
            sanitized=str(exc).replace(token,'[REDACTED]')
            logger.warning('Telegram attempt %d/%d failed: %s',attempt,cfg['telegram_max_attempts'],sanitized)
            if attempt==cfg['telegram_max_attempts']:
                raise RuntimeError(f'Telegram delivery failed: {sanitized}') from None
            time.sleep(cfg['retry_delay_seconds'])


def send_results(cfg,stats,logger):
    mode=cfg['telegram_notification_mode']
    normal=(mode=='ALWAYS' or mode=='ONLY_IF_NEW' and stats['processed']>0 or
            mode=='ONLY_IF_RELEVANT' and stats['relevant']>0)
    blocked=cfg['telegram_notify_on_model_blocked'] and stats['blocked']>0
    if not (normal or blocked):return False
    if normal:
        text=(f"WhatsAppReader — {cfg['group_name']}\n"
              f"Processed: {stats['processed']}\nRelevant: {stats['relevant']}")
        if blocked:text+=f"\nBlocked by Gemini: {stats['blocked']}"
    else:text=f"WhatsAppReader — {cfg['group_name']}\nBlocked by Gemini: {stats['blocked']}"
    return send(text,cfg,logger)


def send_failure(cfg,run_id,stage,error,logger):
    if not cfg['telegram_notify_on_run_failure']:return
    text=f'WhatsAppReader FAILED\nRun #{run_id}\nStage: {stage}\nError: {str(error)[:900]}'
    try:send(text,cfg,logger)
    except Exception as exc:
        # Do not recursively notify about Telegram failure.
        logger.error('Could not deliver failure notification: %s',exc)
