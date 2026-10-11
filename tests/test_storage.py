import json
from datetime import datetime,timedelta,timezone
from whatsappreader.settings import validate
from whatsappreader.storage import Store
from whatsappreader.reader import normalize
from whatsappreader.cleanup import cleanup


def test_settings_default_image_attempts_one():
    assert validate({})['image_max_attempts']==1

def test_invalid_attempts_rejected():
    import pytest
    with pytest.raises(ValueError):validate({'image_max_attempts':0})

def test_atomic_checkpoint_and_dedup(tmp_path):
    db=Store(tmp_path/'reader.db');db.initialize()
    message=normalize({'metadata':'[11:00, 10.10.2026] Alice: ','text':'Casting','direction':'in','hasImage':False})
    db.save_scan('Group',[message],message,1)
    db.save_scan('Group',[message],message,2)
    assert len(db.pending())==1
    assert db.get_checkpoint('Group')['last_message_key']==message['key']
    db.analyze(message['key'],2,'relevant',result={'relevant':True,'score':85})
    assert len(db.pending())==0
    assert len(db.results())==1

def test_cleanup_keeps_checkpoint_and_pending(tmp_path,monkeypatch):
    from whatsappreader import cleanup as module
    from whatsappreader import settings
    monkeypatch.setattr(settings,'deployment',lambda: {'data_dir':str(tmp_path)})
    monkeypatch.setattr(module,'data_path',lambda name:tmp_path/name)
    monkeypatch.setattr(module,'logs_dir',lambda:tmp_path/'logs')
    db=Store(tmp_path/'data.db');db.initialize()
    key='a'*64
    old=(datetime.now(timezone.utc)-timedelta(days=40)).isoformat()
    with db.connect() as c:
        c.execute("INSERT INTO messages(key,chat,text,has_image,status,discovered_at) VALUES(?,?,?,?,?,?)",(key,'Group','hello',0,'PENDING_AI',old))
        c.execute('INSERT INTO checkpoints(chat,last_message_key,updated_at) VALUES(?,?,?)',('Group',key,old))
    import logging
    cleanup(db,validate({}),logging.getLogger('test'),force=True)
    assert db.pending()[0]['key']==key

def test_settings_history_retention(tmp_path,monkeypatch):
    from whatsappreader import cleanup as module
    monkeypatch.setattr(module,'data_path',lambda name:tmp_path/name)
    monkeypatch.setattr(module,'logs_dir',lambda:tmp_path/'logs')
    db=Store(tmp_path/'data.db');db.initialize()
    db.save_settings({'topic':'casting'},'test')
    old=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat()
    with db.connect() as con:
        con.execute('UPDATE settings_history SET updated_at=?',(old,))
    import logging
    results=cleanup(db,validate({}),logging.getLogger('test'),force=True)
    assert results['settings_history']==1


def test_default_image_prompt_is_generic():
    from whatsappreader.settings import DEFAULTS
    prompt = DEFAULTS['gemini_image_prompt']
    assert '{topic}' in prompt
    assert '{text}' in prompt
    assert 'child profile' not in prompt.lower()
    assert 'casting' not in prompt.lower()


def test_web_editable_prompts_survive_reinitialization(tmp_path):
    db = Store(tmp_path / 'settings.db')
    db.initialize()
    prompt = 'Analyse this picture and the message for {topic}. Return the schema-defined result.'
    db.save_settings({'topic': 'Public transportation', 'gemini_image_prompt': prompt}, 'admin')
    db.initialize()
    assert db.settings()['topic'] == 'Public transportation'
    assert db.settings()['gemini_image_prompt'] == prompt
