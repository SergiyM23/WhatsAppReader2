"""One-time, non-destructive transfer of PowerShell JSON history and checkpoint."""
import json
from pathlib import Path
from .reader import normalize,parse_timestamp
from .settings import DEFAULTS,data_path
import shutil
from .storage import utcnow

MAPPING={
 'groupName':'group_name','batchLimit':'batch_limit','maxScrolls':'max_scrolls',
 'maxStagnantScrolls':'max_stagnant_scrolls','topic':'topic','geminiModel':'gemini_model',
 'relevanceThreshold':'relevance_threshold','geminiMaxRetries':'gemini_max_attempts',
 'geminiRequestsPerMinute':'gemini_requests_per_minute',
 'geminiRateLimitWaitSeconds':'gemini_rate_limit_wait_seconds',
 'geminiInterRequestDelaySeconds':'gemini_inter_request_delay_seconds',
 'telegramChatId':'telegram_chat_id','telegramNotificationMode':'telegram_notification_mode',
 'telegramNotifyOnModelBlocked':'telegram_notify_on_model_blocked',
 'telegramNotifyOnRunFailure':'telegram_notify_on_run_failure',
}

def load(path,default):
    if not path.exists():return default
    return json.loads(path.read_text(encoding='utf-8-sig'))

def as_list(obj):
    if isinstance(obj,list):return obj
    return [obj] if isinstance(obj,dict) else []

def import_legacy(store,source:Path):
    source=Path(source)
    data=source/'data' if (source/'data').exists() else source
    # Allow both the project root and a standalone data directory.
    root=source if (source/'config.json').exists() else source.parent
    cfg=load(root/'config.json',{})
    updates={dest:cfg[key] for key,dest in MAPPING.items() if key in cfg and dest in DEFAULTS}
    if updates.get('max_scrolls')==25:
        updates['max_scrolls']=300  # Legacy startup migration from the PowerShell reader.
    if updates:store.save_settings(updates,'legacy-import')
    chat=store.settings()['group_name']
    counts={'messages':0,'analysis':0,'checkpoint':False,'settings':len(updates)}
    inputs=[]
    for filename in ('last-read.json','new-messages.json','pending-messages.json'):
        inputs+=as_list(load(data/filename,[]))
    # Also include messages embedded in archived analysis.
    analyzed=as_list(load(data/'analysis.json',[]))
    archived=as_list(load(data/'relevant-messages.json',[]))
    for record in analyzed+archived:
        if isinstance(record.get('message'),dict):inputs.append(record['message'])
    unique={}
    image_root=data_path('images')
    image_root.mkdir(parents=True,exist_ok=True)
    for item in inputs:
        if not isinstance(item,dict):continue
        if item.get('metadata'):
            m=normalize(item)
            # Respect existing key if it is a SHA256 key from legacy state.
            if isinstance(item.get('key'),str) and len(item['key'])==64:m['key']=item['key']
            original_image=item.get('imagePath','')
            if original_image:
                # Windows absolute paths are not valid on Linux; recover by filename.
                name=str(original_image).replace('\\','/').split('/')[-1]
                existing=data/'images'/name
                target=image_root/name
                if existing.is_file() and not target.exists():shutil.copy2(existing,target)
                m['imagePath']=str(target) if target.is_file() else ''
            m['imageCaptureError']=item.get('imageCaptureError','')
            unique[m['key']]=m
    # Important: do not advance checkpoint automatically based on incomplete inputs.
    if unique:
        with store.connect() as db:
            for m in unique.values():
                db.execute('''INSERT OR IGNORE INTO messages
                (key,chat,message_date,message_time,message_timestamp,author,direction,metadata,text,
                 has_image,image_path,image_error,image_attempts,status,discovered_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                 (m['key'],chat,m['date'],m['time'],m['timestamp'],m['author'],m['direction'],
                  m['metadata'],m['text'],int(m['hasImage']),m['imagePath'] or None,
                  m['imageCaptureError'] or None,0,'PENDING_AI',utcnow()))
                counts['messages']+=1
    for item in archived+analyzed:
        key=item.get('key');status=item.get('status')
        if not key or key not in unique or status not in {'relevant','not_relevant','model_blocked','image_missing','empty_message'}:
            continue
        classification=item.get('classification') or {}
        result={'score':classification.get('score'), 'relevant':classification.get('relevant',False),
                'reason':classification.get('reason'),
                'matched_aspects':classification.get('matchedAspects',[]),
                'model':classification.get('model'),'interaction_id':classification.get('interactionId')}
        store.analyze(key,None,status,result=result,error=item.get('error'))
        counts['analysis']+=1
    state=load(data/'state.json',{})
    key=state.get('lastProcessedKey')
    if key and not store.get_checkpoint(chat):
        import re
        metadata=state.get('lastProcessedMetadata','')
        if not re.fullmatch(r'[0-9a-fA-F]{64}',key):
            raise ValueError('Legacy checkpoint key is invalid; check state.json before importing.')
        if len(re.findall(r'\[\d{1,2}:\d{2},\s*\d{1,2}\.\d{1,2}\.\d{4}\]',metadata))!=1:
            raise ValueError('Legacy checkpoint metadata is invalid; check state.json before importing.')
        if state.get('groupName') and state['groupName']!=chat:
            raise ValueError('Legacy checkpoint belongs to a different WhatsApp group.')
        stamp=state.get('lastProcessedDateTime')
        if stamp:
            try:
                from datetime import datetime
                stamp=datetime.fromisoformat(stamp).isoformat(timespec='minutes')
            except ValueError:stamp=None
        if not stamp:
            import re
            m=re.match(r'^\[([^,]+),\s*([^\]]+)\]',state.get('lastProcessedMetadata',''))
            if m:stamp=parse_timestamp(m.group(2),m.group(1))
        with store.connect() as db:
            db.execute('INSERT INTO checkpoints(chat,last_message_key,last_metadata,last_timestamp,updated_at) VALUES(?,?,?,?,?)',
                       (chat,key,state.get('lastProcessedMetadata'),stamp,utcnow()))
        counts['checkpoint']=True
    return counts
