import json
from whatsappreader.storage import Store
from whatsappreader.import_legacy import import_legacy
from whatsappreader.reader import normalize


def test_import_state_and_pending_and_config(tmp_path,monkeypatch):
    from whatsappreader import import_legacy as importer
    monkeypatch.setattr(importer,'data_path',lambda name:tmp_path/'dest'/name)
    db=Store(tmp_path/'target.db');db.initialize()
    source=tmp_path/'windows';(source/'data').mkdir(parents=True)
    (source/'config.json').write_text(json.dumps({'groupName':'Old Group','maxScrolls':25,'topic':'casting'}),encoding='utf-8')
    msg=normalize({'metadata':'[10:20, 10.10.2026] Alice:','text':'Test','direction':'in'})
    (source/'data'/'pending-messages.json').write_text(json.dumps([msg]),encoding='utf-8')
    (source/'data'/'state.json').write_text(json.dumps({'groupName':'Old Group',
       'lastProcessedKey':msg['key'],'lastProcessedMetadata':msg['metadata']}),encoding='utf-8')
    result=import_legacy(db,source)
    assert result['messages']==1 and result['checkpoint']
    assert db.settings()['max_scrolls']==300
    assert db.get_checkpoint('Old Group')['last_message_key']==msg['key']
    assert db.pending()[0]['text']=='Test'
