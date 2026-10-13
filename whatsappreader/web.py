"""English administrative UI. Bind only to loopback behind nginx HTTPS Basic Auth."""
from __future__ import annotations
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI,Depends,Form,HTTPException,Request
from fastapi.responses import HTMLResponse,RedirectResponse,StreamingResponse,FileResponse,JSONResponse
from fastapi.security import HTTPBasic,HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from .settings import data_path,deployment,DEFAULTS
from .storage import Store

app=FastAPI(title='WhatsAppReader Console',docs_url=None,redoc_url=None,openapi_url=None)
templates=Jinja2Templates(directory=str(Path(__file__).parent/'templates'))


def madrid_time(value):
    if not value:return '—'
    try:return datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/Madrid')).strftime('%d %b %Y, %H:%M:%S')
    except (ValueError,TypeError):return str(value)

templates.env.filters['madrid_time']=madrid_time
security=HTTPBasic()

def authorized(credentials:HTTPBasicCredentials=Depends(security)):
    username=os.getenv('WA_ADMIN_USER','admin')
    password=os.getenv('WA_ADMIN_PASSWORD','')
    if not password or not (hmac.compare_digest(credentials.username,username) and
                           hmac.compare_digest(credentials.password,password)):
        raise HTTPException(401,'Authentication required',headers={'WWW-Authenticate':'Basic'})
    return credentials.username

def check_csrf(token):
    expected=os.getenv('WA_CSRF_TOKEN','')
    if not expected or not hmac.compare_digest(str(token),expected):
        raise HTTPException(403,'Invalid request token.')

def db():
    store=Store();store.initialize();return store

def page(request,template,**values):
    values.setdefault('base','/whatsappreader')
    values.setdefault('csrf',os.getenv('WA_CSRF_TOKEN',''))
    return templates.TemplateResponse(request,template,values)

def next_run():
    try:
        r=subprocess.run(['systemctl','show','whatsappreader.timer','--property=NextElapseUSecRealtime','--value'],
                         capture_output=True,text=True,timeout=3)
        value=r.stdout.strip()
        return value if r.returncode==0 and value not in ('','n/a') else 'Not available'
    except Exception:return 'Not available'

@app.get('/',include_in_schema=False)
def root():return RedirectResponse('/whatsappreader/')

@app.get('/whatsappreader/',response_class=HTMLResponse)
def dashboard(request:Request,user=Depends(authorized)):
    store=db()
    runs=store.recent_runs(10)
    return page(request,'dashboard.html',running=store.running(),runs=runs,
                last=runs[0] if runs else None,next_time=next_run(),settings=store.settings())

@app.get('/whatsappreader/status')
def dashboard_status(user=Depends(authorized)):
    """Provide lightweight polling data without reloading the whole dashboard."""
    store=db()
    running=store.running()
    recent=store.recent_runs(1)
    last=recent[0] if recent else None
    return JSONResponse({
        'running_id': running['id'] if running else None,
        'running_stage': running['stage'] if running else None,
        'last_id': last['id'] if last else None,
        'last_status': last['status'] if last else None,
    },headers={'Cache-Control':'no-store'})

@app.post('/whatsappreader/run')
def manual_run(csrf:str=Form(...),user=Depends(authorized)):
    check_csrf(csrf)
    if db().running():raise HTTPException(409,'A run is already active.')
    subprocess.Popen([sys.executable,'-m','whatsappreader','run','--trigger','manual'],
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     start_new_session=True,cwd=str(Path(__file__).parents[1]))
    return RedirectResponse('/whatsappreader/',status_code=303)

@app.get('/whatsappreader/results',response_class=HTMLResponse)
def results(request:Request,day:str='',user=Depends(authorized)):
    if day:
        try:datetime.strptime(day,'%Y-%m-%d')
        except ValueError:raise HTTPException(400,'Date must use YYYY-MM-DD.')
    return page(request,'results.html',rows=db().results(day=day or None),day=day)

@app.get('/whatsappreader/logs',response_class=HTMLResponse)
def logs(request:Request,run_id:int=0,user=Depends(authorized)):
    store=db();runs=store.recent_runs(150)
    if not run_id and runs:run_id=runs[0]['id']
    return page(request,'logs.html',runs=runs,run_id=run_id,rows=store.log_rows(run_id,0,1000))

@app.get('/whatsappreader/logs/stream/{run_id}')
def log_stream(run_id:int,user=Depends(authorized)):
    def events():
        last=0
        for _ in range(3600):
            rows=db().log_rows(run_id,last,200)
            for item in rows:
                last=item['id']
                yield 'data: '+json.dumps(item,ensure_ascii=False)+'\n\n'
            if not rows:
                with db().connect() as con:
                    run=con.execute('SELECT status FROM runs WHERE id=?',(run_id,)).fetchone()
                if not run or run['status']!='RUNNING':
                    yield 'event: finished\ndata: {}\n\n'
                    return
                yield ': keepalive\n\n'
            time.sleep(1)
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

CONFIG_GROUPS={
    'WhatsApp': ['group_name','batch_limit','max_scrolls','max_stagnant_scrolls','collector_max_attempts',
                 'image_max_attempts'],
    'Gemini': ['topic','gemini_model','gemini_text_prompt','gemini_image_prompt',
               'relevance_threshold','gemini_max_attempts','gemini_requests_per_minute',
               'gemini_rate_limit_wait_seconds','gemini_inter_request_delay_seconds'],
    'Telegram': ['telegram_chat_id','telegram_notification_mode',
                 'telegram_notify_on_model_blocked','telegram_notify_on_run_failure',
                 'telegram_max_attempts','retry_delay_seconds'],
    'Retention / Cleanup': ['retention_messages_days','retention_analysis_days',
               'retention_logs_days','retention_log_files_days','retention_reports_days',
               'retention_images_days','retention_runs_days','retention_settings_history_days','cleanup_interval_hours'],
    'Scheduling': ['schedule','report_max_attempts']
}


def config_view(request,settings,message=''):
    return page(request,'config.html',settings=settings,groups=CONFIG_GROUPS,
                config_text=json.dumps(settings,ensure_ascii=False,indent=2),message=message)


def save_and_update(updates,user):
    previous=db().settings()
    if 'schedule' in updates and updates['schedule']!=previous['schedule']:
        value=updates['schedule']
        if not isinstance(value,str):raise ValueError('Schedule must be a calendar expression.')
        valid=subprocess.run(['systemd-analyze','calendar',value],
                             capture_output=True,text=True,timeout=8)
        if valid.returncode!=0:raise ValueError('Invalid systemd calendar expression: '+valid.stderr[:200])
    new=db().save_settings(updates,user)
    message='Settings saved. Changes will apply to the next run.'
    if previous['schedule']!=new['schedule']:
        cmd=['sudo','-n','/usr/local/sbin/whatsappreader-apply-schedule']
        result=subprocess.run(cmd,timeout=15,capture_output=True,text=True)
        if result.returncode!=0:
            message+=' WARNING: systemd timer update failed: '+(result.stderr or result.stdout)[:400]
        else:message+=' systemd timer updated.'
    return new,message

@app.get('/whatsappreader/config',response_class=HTMLResponse)
def config_page(request:Request,user=Depends(authorized)):
    return config_view(request,db().settings())

@app.post('/whatsappreader/config/fields',response_class=HTMLResponse)
async def save_config_fields(request:Request,user=Depends(authorized)):
    form=await request.form()
    check_csrf(form.get('csrf',''))
    keys={k for group in CONFIG_GROUPS.values() for k in group}
    updates={}
    try:
        for key in keys:
            default=DEFAULTS[key]
            if isinstance(default,bool):updates[key]=form.get(key)=='on'
            elif type(default) is int:updates[key]=int(form[key])
            else:updates[key]=str(form[key])
        cfg,message=save_and_update(updates,user)
    except (ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as exc:
        cfg=db().settings()
        message=f'Validation error: {exc}'
    return config_view(request,cfg,message)

@app.post('/whatsappreader/config',response_class=HTMLResponse)
def save_config(request:Request,config_text:str=Form(...),csrf:str=Form(...),user=Depends(authorized)):
    check_csrf(csrf)
    try:
        cfg,message=save_and_update(json.loads(config_text),user)
    except (ValueError,TypeError,subprocess.TimeoutExpired) as exc:
        cfg=db().settings()
        message=f'Validation error: {exc}'
    return config_view(request,cfg,message)

@app.get('/whatsappreader/session',response_class=HTMLResponse)
def session_page(request:Request,user=Depends(authorized)):
    with db().connect() as con:
        row=con.execute("SELECT value FROM housekeeping WHERE name='login_status'").fetchone()
    return page(request,'session.html',state=row['value'] if row else 'UNKNOWN')

@app.post('/whatsappreader/session/login')
def start_login(csrf:str=Form(...),user=Depends(authorized)):
    check_csrf(csrf)
    if db().running():raise HTTPException(409,'A collection run is already active.')
    p=data_path('qr-session.log');p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('wb') as stream:
        subprocess.Popen([sys.executable,'-m','whatsappreader','login'],stdin=subprocess.DEVNULL,
                         stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                         cwd=str(Path(__file__).parents[1]))
    return RedirectResponse('/whatsappreader/session',status_code=303)

@app.get('/whatsappreader/browser',response_class=HTMLResponse)
def browser_page(request:Request,user=Depends(authorized)):
    return page(request,'browser.html',result='',config=deployment())

@app.post('/whatsappreader/browser/test',response_class=HTMLResponse)
def browser_test(request:Request,csrf:str=Form(...),user=Depends(authorized)):
    check_csrf(csrf)
    if db().running():raise HTTPException(409,'Wait for the active run to finish.')
    try:
        proc=subprocess.run([sys.executable,'-m','whatsappreader','browser-test'],capture_output=True,
                            text=True,timeout=60)
        result='PASS: '+proc.stdout if proc.returncode==0 else 'FAILED: '+proc.stderr
    except subprocess.TimeoutExpired:result='FAILED: Browser test timed out.'
    return page(request,'browser.html',result=result,config=deployment())

@app.get('/whatsappreader/image/{message_key}')
def view_image(message_key:str,user=Depends(authorized)):
    with db().connect() as con:
        row=con.execute('SELECT image_path FROM messages WHERE key=?',(message_key,)).fetchone()
    if not row or not row['image_path']:raise HTTPException(404,'Image not available.')
    path=Path(row['image_path']).resolve();root=data_path('images').resolve()
    if not path.is_relative_to(root) or not path.is_file():raise HTTPException(404,'Image not available.')
    return FileResponse(path,media_type='image/png')

@app.get('/whatsappreader/report/{run_id}')
def download_report(run_id:int,user=Depends(authorized)):
    with db().connect() as con:
        row=con.execute('SELECT report_path FROM runs WHERE id=?',(run_id,)).fetchone()
    if not row or not row['report_path']:raise HTTPException(404,'No report for this run.')
    path=Path(row['report_path']).resolve();root=data_path('reports').resolve()
    if not path.is_relative_to(root) or not path.is_file():raise HTTPException(404,'Report file unavailable.')
    return FileResponse(path,media_type='text/html',filename=path.name)
