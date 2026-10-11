"""Generate English HTML reports for each run from persisted results."""
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
from .settings import data_path


def generate(store,run_id,cfg):
    with store.connect() as db:
        rows=[dict(r) for r in db.execute('''SELECT m.*,a.status AS result_status,a.score,a.reason,a.error,
           a.matched_aspects_json FROM analysis a JOIN messages m ON m.key=a.message_key
           WHERE a.run_id=? ORDER BY m.message_timestamp''',(run_id,))]
        backlog=db.execute("SELECT COUNT(*) FROM messages WHERE status='PENDING_AI'").fetchone()[0]
    now=datetime.now(ZoneInfo('Europe/Madrid'))
    timestamp=now.strftime('%Y-%m-%d_%H%M%S')
    directory=data_path('reports');directory.mkdir(parents=True,exist_ok=True)
    path=directory/f'report_{timestamp}.html'
    cards=[]
    for r in rows:
        result=r['result_status'];score=r['score'];reason=r['reason'] or r['error'] or ''
        tags=''
        if r['matched_aspects_json']:
            import json
            tags=', '.join(json.loads(r['matched_aspects_json']))
        image_html = ''
        if r['image_path']:
            from pathlib import Path
            image_file=Path(r['image_path'])
            if image_file.is_file():
                image_html=f'<img style="max-width:100%;max-height:480px" src="../images/{escape(image_file.name)}" alt="WhatsApp image">'
        cards.append(f'<article><div class="meta">{escape(r["message_date"] or "")} '
                     f'{escape(r["message_time"] or "")} — {escape(r["author"] or "")}</div>'
                     f'<h3>{escape(result)} {"" if score is None else str(score)+"%"}</h3>'
                     f'{image_html}<p class="msg">{escape(r["text"] or "")}</p>'
                     f'<p>{escape(reason)}</p><small>{escape(tags)}</small></article>')
    body='\n'.join(cards) or '<p>No messages analyzed in this run.</p>'
    document='''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>WhatsAppReader Report</title>
<style>body{font:16px system-ui;max-width:950px;margin:45px auto;padding:0 18px;background:#f5f7fb;color:#172538}
article{background:white;padding:20px;border-radius:12px;margin:14px 0;border:1px solid #e1e5ea}
.meta{color:#596a7c;font-size:13px}.msg{white-space:pre-wrap}small{color:#66768a}</style></head><body>'''
    document+=f'<h1>WhatsAppReader — Run #{run_id}</h1><p>{escape(now.isoformat())} · Topic: {escape(cfg["topic"])}</p>'
    document+=f'<p>Results: {len(rows)} · Pending: {backlog}</p>'+body+'</body></html>'
    path.write_text(document,encoding='utf-8')
    return path
