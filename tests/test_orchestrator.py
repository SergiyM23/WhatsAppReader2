from whatsappreader.storage import Store
from whatsappreader.orchestrator import execute


def test_failed_collector_still_sends_telegram_and_cleanups(tmp_path,monkeypatch):
    from whatsappreader import settings,orchestrator
    monkeypatch.setattr(settings,'deployment',lambda: {'data_dir':str(tmp_path)})
    monkeypatch.setattr(orchestrator,'data_path',lambda name:tmp_path/name)
    from whatsappreader import logging_service,cleanup
    monkeypatch.setattr(logging_service,'logs_dir',lambda:tmp_path/'logs')
    monkeypatch.setattr(cleanup,'data_path',lambda name:tmp_path/name)
    db=Store(tmp_path/'db.sqlite');db.initialize()
    calls=[]
    monkeypatch.setattr(orchestrator.telegram,'send_failure',lambda *a,**k:calls.append('telegram'))
    monkeypatch.setattr(orchestrator.cleanup,'cleanup',lambda *a,**k:calls.append('cleanup'))
    def broken(*a):raise RuntimeError('WhatsApp disconnected')
    status,run_id=execute('manual',db,collector_fn=broken)
    assert status=='FAILED'
    assert calls==['telegram','cleanup']
    assert db.recent_runs()[0]['status']=='FAILED'
    assert list((tmp_path/'logs').glob('run_*.log'))
