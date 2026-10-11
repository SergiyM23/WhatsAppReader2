"""Validated runtime settings, separated from machine paths and credentials."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = {
    "group_name": "",
    "batch_limit": 100,
    "max_scrolls": 300,
    "max_stagnant_scrolls": 6,
    "image_max_attempts": 1,
    "collector_max_attempts": 1,
    "report_max_attempts": 1,
    "topic": "",
    "gemini_model": "gemini-3.5-flash-lite",
    "gemini_text_prompt": (
        "You are filtering messages from a WhatsApp group for one specific user interest.\n\n"
        "INTERESTING TOPIC:\n{topic}\n\nMESSAGE METADATA:\nAuthor: {author}\nDate: {date}\nTime: {time}\n\n"
        "MESSAGE:\n{text}\n\nTask: Decide whether this message is relevant to the interesting topic.\n"
        "Rules:\n- Judge semantic meaning, not only keyword matches.\n"
        "- Include indirect but clearly useful matches.\n"
        "- Do not mark a message relevant merely because it contains a vague related word.\n"
        "- score must be from 0 to 100.\n- reason must be short and practical.\n"
        "- matched_aspects should list the concrete parts of the topic that matched.\n"
        "- Return only the schema-defined result."
    ),
    "gemini_image_prompt": (
        "You are filtering WhatsApp messages for a user-defined topic.\n\n"
        "INTERESTING TOPIC:\n{topic}\n\nMESSAGE METADATA:\nAuthor: {author}\nDate: {date}\nTime: {time}\n\n"
        "WHATSAPP CAPTION / TEXT:\n{text}\n\nAn image of the WhatsApp message is attached.\n"
        "Task: Decide whether the combined image and message text are relevant to the topic.\n"
        "Rules:\n- Read and consider any visible text in the image.\n"
        "- Consider the meaning of the message, including useful indirect matches.\n"
        "- Do not assume relevance merely because one related word appears.\n"
        "- score must be from 0 to 100.\n"
        "- reason must be short and practical.\n"
        "- matched_aspects should describe concrete topic aspects that match.\n"
        "- Return only the schema-defined result."
    ),
    "relevance_threshold": 70,
    "gemini_max_attempts": 3,
    "gemini_requests_per_minute": 10,
    "gemini_rate_limit_wait_seconds": 60,
    "gemini_inter_request_delay_seconds": 1,
    "telegram_chat_id": "",
    "telegram_notification_mode": "ALWAYS",
    "telegram_notify_on_model_blocked": True,
    "telegram_notify_on_run_failure": True,
    "telegram_max_attempts": 3,
    "retry_delay_seconds": 5,
    "retention_messages_days": 30,
    "retention_analysis_days": 30,
    "retention_logs_days": 30,
    "retention_log_files_days": 30,
    "retention_reports_days": 30,
    "retention_images_days": 30,
    "retention_runs_days": 30,
    "retention_settings_history_days": 30,
    "cleanup_interval_hours": 24,
    "schedule": "*-*-* 20:00:00 Europe/Madrid",
}

BOUNDS = {
    "batch_limit": (1,1000), "max_scrolls": (1,3000), "max_stagnant_scrolls":(1,50),
    "image_max_attempts":(1,20), "collector_max_attempts":(1,10), "report_max_attempts":(1,10), "relevance_threshold":(0,100),
    "gemini_max_attempts":(1,20),"gemini_requests_per_minute":(1,500),
    "gemini_rate_limit_wait_seconds":(1,3600),"gemini_inter_request_delay_seconds":(0,60),
    "telegram_max_attempts":(1,10), "retry_delay_seconds":(0,3600),
    "retention_messages_days":(1,36500), "retention_analysis_days":(1,36500),
    "retention_logs_days":(1,36500), "retention_log_files_days":(1,36500),
    "retention_reports_days":(1,36500), "retention_images_days":(1,36500),
    "retention_runs_days":(1,36500),"retention_settings_history_days":(1,36500),"cleanup_interval_hours":(1,8760),
}


def validate(settings: dict) -> dict:
    if not isinstance(settings,dict): raise ValueError('Settings must be a JSON object.')
    unknown = set(settings)-set(DEFAULTS)
    if unknown: raise ValueError('Unknown settings: '+', '.join(sorted(unknown)))
    out = copy.deepcopy(DEFAULTS)
    out.update(settings)
    for k,(minimum,maximum) in BOUNDS.items():
        v=out[k]
        if type(v) is not int or not minimum <= v <= maximum:
            raise ValueError(f'{k} must be an integer between {minimum} and {maximum}.')
    for k in ('group_name','topic','gemini_model','gemini_text_prompt','gemini_image_prompt',
              'telegram_chat_id','telegram_notification_mode','schedule'):
        if not isinstance(out[k],str): raise ValueError(f'{k} must be a string.')
    for k in ('telegram_notify_on_model_blocked','telegram_notify_on_run_failure'):
        if not isinstance(out[k],bool): raise ValueError(f'{k} must be a boolean.')
    if out['telegram_notification_mode'] not in {'ALWAYS','ONLY_IF_NEW','ONLY_IF_RELEVANT','NEVER'}:
        raise ValueError('Invalid Telegram notification mode.')
    for prompt_key in ('gemini_text_prompt','gemini_image_prompt'):
        import string
        keys={field for _,field,_,_ in string.Formatter().parse(out[prompt_key]) if field}
        if not keys.issubset({'topic','author','date','time','text'}):
            raise ValueError(f'Unsupported template placeholder in {prompt_key}: {keys}')
    if '\n' in out['schedule'] or not out['schedule'].strip():
        raise ValueError('Invalid systemd calendar schedule.')
    return out


def deployment() -> dict:
    path=Path(os.getenv('WA_READER_CONFIG',str(ROOT/'app.yaml')))
    data=yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(data,dict): raise ValueError('Invalid deployment file.')
    out={"data_dir":str(ROOT/'data'),"logs_dir":str(ROOT/'logs'),"browser_binary":"/usr/bin/chromium-browser",
         "driver_binary":"/usr/bin/chromedriver",
         "browser_profile":"/home/ubuntu/snap/chromium/common/whatsapp-profile",
         "qr_screenshot":"/var/www/whatsapp-qr/whatsapp-live.png",
         "web_host":"127.0.0.1","web_port":8765}
    out.update(data)
    out['data_dir']=str(Path(out['data_dir']).expanduser())
    out['logs_dir']=str(Path(out['logs_dir']).expanduser())
    return out


def data_path(name: str) -> Path:
    return Path(deployment()['data_dir'])/name


def logs_dir() -> Path:
    """Flat run log archive directory, separate from the SQLite data directory."""
    return Path(deployment()['logs_dir'])
