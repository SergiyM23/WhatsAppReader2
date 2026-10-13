"""Gemini Interactions API classification with schema-constrained JSON and limited retries."""
from __future__ import annotations
import base64
import json
import os
import time
from pathlib import Path
import httpx

URL='https://generativelanguage.googleapis.com/v1beta/interactions'
SCHEMA={
    'type':'object','properties':{
        'relevant':{'type':'boolean'},'score':{'type':'integer','minimum':0,'maximum':100},
        'reason':{'type':'string'},'matched_aspects':{'type':'array','items':{'type':'string'}}
    },'required':['relevant','score','reason','matched_aspects'],'additionalProperties':False
}

class ModelBlocked(Exception):pass


def is_blocked(detail):
    lowered=detail.lower()
    return any(x in lowered for x in ('input blocked','prohibited use','sensitive words','prompt could not be submitted','prohibited_content'))


def is_rate_limited(detail):
    lowered=detail.lower()
    return any(x in lowered for x in ('429','resource_exhausted','rate limit','quota'))


def classify(message,cfg):
    key=os.getenv('GEMINI_API_KEY','')
    if not key:raise RuntimeError('GEMINI_API_KEY is not configured.')
    is_image=bool(message['has_image'])
    template=cfg['gemini_image_prompt'] if is_image else cfg['gemini_text_prompt']
    prompt=template.format(topic=cfg['topic'],author=message['author'] or '',
                           date=message['message_date'] or '',time=message['message_time'] or '',
                           text=message['text'] or '')
    payload_input=prompt
    if is_image:
        path=message.get('image_path')
        if not path or not Path(path).is_file():raise FileNotFoundError('WhatsApp image screenshot is missing.')
        payload_input=[{'type':'text','text':prompt},
                       {'type':'image','data':base64.b64encode(Path(path).read_bytes()).decode('ascii'),
                        'mime_type':'image/png'}]
    body={'model':cfg['gemini_model'],'input':payload_input,
          'response_format':{'type':'text','mime_type':'application/json','schema':SCHEMA},
          'store':False,'generation_config':{'max_output_tokens':300,'thinking_level':'minimal'}}
    with httpx.Client(timeout=90) as client:
        response=client.post(URL,json=body,headers={'x-goog-api-key':key})
        try:response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail=response.text[:1200]
            if is_blocked(detail):raise ModelBlocked(detail) from exc
            raise RuntimeError(f'Gemini HTTP {response.status_code}: {detail}') from exc
        data=response.json()
    if data.get('status','completed')!='completed':
        raise RuntimeError(f"Gemini interaction status: {data.get('status')}")
    content=next((c.get('text') for step in data.get('steps',[]) if step.get('type')=='model_output'
                  for c in step.get('content',[]) if c.get('type')=='text' and c.get('text')),None)
    if not content:raise RuntimeError('Gemini response contained no model output text.')
    try:
        result=json.loads(content)
        score=result['score']
        if type(score) is not int or not 0<=score<=100:raise ValueError('Invalid score')
        if type(result['relevant']) is not bool:raise ValueError('Invalid relevant flag')
        if not isinstance(result['reason'],str) or not isinstance(result['matched_aspects'],list):
            raise ValueError('Invalid classification schema')
    except (ValueError,KeyError,TypeError) as exc:
        raise RuntimeError('Gemini returned an invalid classification result.') from exc
    result['model']=data.get('model',cfg['gemini_model'])
    result['interaction_id']=data.get('id','')
    return result


def _message_label(message, index, total):
    """Identify a message without exposing its long internal hash in routine logs."""
    date = ' '.join(str(message.get('message_date') or '').split())
    time = ' '.join(str(message.get('message_time') or '').split())
    when = f'{date} {time}'.strip() or 'Unknown date'
    author = ' '.join(str(message.get('author') or '').split())
    if not author:
        author = 'You' if message.get('direction') == 'out' else 'Unknown author'
    return f'[{index}/{total}] {when} | {author}'


def analyze_pending(store,run_id,cfg,logger):
    """Run through pending messages once; terminal errors stop this orchestrator run."""
    if not cfg['topic'].strip():raise RuntimeError('Gemini topic is not configured.')
    pending=store.pending()
    logger.info('Gemini analysis queue: %d pending message(s).',len(pending))
    processed=relevant=blocked=0
    in_window=0
    for index,message in enumerate(pending,start=1):
        key=message['key']
        label=_message_label(message,index,len(pending))
        if message['has_image'] and (not message.get('image_path') or not Path(message['image_path']).is_file()):
            store.analyze(key,run_id,'image_missing',error=message.get('image_error') or 'Image screenshot missing.')
            logger.warning('%s -> image_missing (%s capture attempt(s)).',label,message['image_attempts'])
            processed+=1
            continue
        if not message['has_image'] and not message['text'].strip():
            store.analyze(key,run_id,'empty_message')
            logger.info('%s -> empty_message',label)
            processed+=1
            continue
        done=False
        for attempt in range(1,cfg['gemini_max_attempts']+1):
            if in_window>=cfg['gemini_requests_per_minute']:
                logger.info('Gemini rate-limit pause: waiting %ds...',cfg['gemini_rate_limit_wait_seconds'])
                time.sleep(cfg['gemini_rate_limit_wait_seconds']);in_window=0
            in_window+=1
            try:
                result=classify(message,cfg)
                status='relevant' if result['relevant'] and result['score']>=cfg['relevance_threshold'] else 'not_relevant'
                store.analyze(key,run_id,status,result=result)
                processed+=1;relevant+=int(status=='relevant');done=True
                logger.info('%s -> %s, score %d',label,status,result['score'])
                break
            except ModelBlocked as exc:
                store.analyze(key,run_id,'model_blocked',error=str(exc))
                logger.warning('%s -> model_blocked: %s',label,exc)
                processed+=1;blocked+=1;done=True
                break
            except Exception as exc:
                logger.warning('%s -> Gemini attempt %d/%d failed: %s',
                               label,attempt,cfg['gemini_max_attempts'],exc)
                if attempt>=cfg['gemini_max_attempts']:
                    # Leave message PENDING_AI, stop the run, notify via orchestrator.
                    store.record_api_error(key,run_id,str(exc))
                    raise RuntimeError(f'Gemini retries exhausted for message {key}: {exc}') from exc
                wait=cfg['gemini_rate_limit_wait_seconds'] if is_rate_limited(str(exc)) else cfg['retry_delay_seconds']
                time.sleep(wait)
                if is_rate_limited(str(exc)):in_window=0
            finally:
                delay=cfg['gemini_inter_request_delay_seconds']
                if delay:time.sleep(delay)
        if not done:raise RuntimeError('Gemini analysis stopped before completing a message.')
    logger.info('Gemini analysis complete: processed=%d relevant=%d blocked=%d',processed,relevant,blocked)
    return {'processed':processed,'relevant':relevant,'blocked':blocked}
