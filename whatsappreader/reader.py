"""WhatsApp message normalization and checkpoint boundary rules (browser-independent)."""
from __future__ import annotations
from datetime import datetime
import hashlib
import re

META = re.compile(r'^\[(?P<time>[^,\]]+),\s*(?P<date>[^\]]+)\]\s*(?P<author>.*?):\s*$')

def parse_timestamp(date,time):
    for fmt in ('%d.%m.%Y %H:%M','%d.%m.%Y %H:%M:%S'):
        try: return datetime.strptime(f'{date} {time}',fmt).isoformat(timespec='minutes')
        except (TypeError,ValueError):pass
    return None

def normalize(raw):
    metadata=str(raw.get('metadata') or '').strip()
    text=re.sub(r'(\n[ \t]*){3,}', '\n\n',str(raw.get('text') or '').replace('\r\n','\n')).strip()
    match=META.match(metadata)
    date,time,author=('', '', '')
    if match:time,date,author=(match.group(k).strip() for k in ('time','date','author'))
    direction=str(raw.get('direction') or '')
    has_image=bool(raw.get('hasImage',False))
    # Matches legacy Get-MessageKey to avoid duplicate imports after migration.
    clean=re.sub(r'\s+',' ',text).strip()[:256]
    key=hashlib.sha256(f'{metadata}|{direction}|{str(has_image)}|{clean}'.encode('utf-8')).hexdigest()
    return dict(key=key,date=date,time=time,author=author,direction=direction,metadata=metadata,
                text=text,hasImage=has_image,timestamp=parse_timestamp(date,time),
                imagePath='',imageCaptureError='',imageAttempts=0)

def chronological(batches):
    """Reverse batches, retaining unique message keys in oldest-to-newest order."""
    ordered=[]; seen=set()
    for batch in reversed(batches):
        for m in batch:
            if m['key'] not in seen:
                seen.add(m['key']);ordered.append(m)
    return ordered

def boundary(batch,checkpoint):
    if checkpoint is None:return 'baseline'
    key=checkpoint['last_message_key']
    if any(m['key']==key for m in batch):return 'exact'
    last=checkpoint.get('last_timestamp')
    if last and any(m.get('timestamp') and m['timestamp']<last for m in batch):return 'timestamp'
    return None

def new_since(messages,checkpoint,mode):
    if mode=='baseline':return []
    if mode=='bounded':return messages
    if mode=='exact':
        idx=next((i for i,m in enumerate(messages) if m['key']==checkpoint['last_message_key']),None)
        if idx is None:raise ValueError('Exact checkpoint is missing from collected messages.')
        return messages[idx+1:]
    if mode=='timestamp':
        older=[i for i,m in enumerate(messages) if m.get('timestamp') and m['timestamp']<checkpoint['last_timestamp']]
        if not older:raise ValueError('Timestamp fallback boundary is missing.')
        return messages[older[-1]+1:]
    raise ValueError(f'Unknown checkpoint mode: {mode}')
