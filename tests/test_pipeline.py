"""End-to-end tests without WhatsApp/Gemini/Telegram network dependencies."""
import logging
from pathlib import Path
import pytest
from whatsappreader.reader import normalize
from whatsappreader.storage import Store
from whatsappreader import gemini,orchestrator


def test_full_run_persists_results_and_archived_logs(tmp_path,monkeypatch):
    from whatsappreader import settings,logging_service,cleanup
    monkeypatch.setattr(settings,'deployment',lambda:{'data_dir':str(tmp_path),'logs_dir':str(tmp_path/'logs')})
    monkeypatch.setattr(orchestrator,'data_path',lambda n:tmp_path/n)
    monkeypatch.setattr(logging_service,'logs_dir',lambda:tmp_path/'logs')
    monkeypatch.setattr(cleanup,'data_path',lambda n:tmp_path/n)
    monkeypatch.setattr(cleanup,'logs_dir',lambda:tmp_path/'logs')
    from whatsappreader import reports
    monkeypatch.setattr(reports,'data_path',lambda n:tmp_path/n)
    db=Store(tmp_path/'test.db');db.initialize()
    db.save_settings({'group_name':'Test Group','topic':'casting',
                      'gemini_inter_request_delay_seconds':0,'telegram_notification_mode':'NEVER'})
    def simulated_collector(store,run_id,cfg,logger):
        m=normalize({'metadata':'[20:00, 10.10.2026] Alex: ','text':'Casting for a child',
                     'direction':'in','hasImage':False})
        store.save_scan(cfg['group_name'],[m],m,run_id)
        return 1
    monkeypatch.setattr(gemini,'classify',lambda message,cfg:{'relevant':True,'score':92,
          'reason':'Relevant casting','matched_aspects':['casting'],'model':'test','interaction_id':'i1'})
    status,run_id=orchestrator.execute('manual',store=db,collector_fn=simulated_collector)
    assert status=='SUCCESS'
    assert db.recent_runs()[0]['status']=='SUCCESS'
    assert db.results()[0]['score']==92
    assert db.results()[0]['analysis_status']=='relevant'
    assert Path(db.recent_runs()[0]['report_path']).exists()
    assert len(list((tmp_path/'logs').glob('run_*.log')))==1


def test_gemini_error_keeps_message_pending(tmp_path,monkeypatch):
    store=Store(tmp_path/'test.db');store.initialize()
    msg=normalize({'metadata':'[09:00, 10.10.2026] A: ','text':'Hello','direction':'in'})
    store.save_scan('Group',[msg],msg,1)
    config=store.settings()
    config.update(topic='casting',gemini_max_attempts=2,
                  gemini_inter_request_delay_seconds=0,retry_delay_seconds=0)
    def failed(*args):raise RuntimeError('503 Service Unavailable')
    monkeypatch.setattr(gemini,'classify',failed)
    with pytest.raises(RuntimeError,match='retries exhausted'):
        gemini.analyze_pending(store,1,config,logging.getLogger('test'))
    assert len(store.pending())==1
    with store.connect() as con:
        assert con.execute('SELECT status FROM analysis').fetchone()[0]=='api_error'
