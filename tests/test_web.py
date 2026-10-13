import os
from fastapi.testclient import TestClient
from whatsappreader.web import app
from whatsappreader.storage import Store


def test_web_auth_and_dashboard(tmp_path,monkeypatch):
    from whatsappreader import web
    db=Store(tmp_path/'db.sqlite');db.initialize()
    monkeypatch.setattr(web,'db',lambda:db)
    monkeypatch.setenv('WA_ADMIN_USER','admin')
    monkeypatch.setenv('WA_ADMIN_PASSWORD','a-long-admin-password')
    monkeypatch.setenv('WA_CSRF_TOKEN','a-csrf-secret')
    client=TestClient(app)
    assert client.get('/whatsappreader/').status_code==401
    auth=('admin','a-long-admin-password')
    result=client.get('/whatsappreader/',auth=auth)
    assert result.status_code==200
    assert 'Next scheduled run' in result.text
    bad=client.post('/whatsappreader/config',data={'csrf':'wrong','config_text':'{}'},auth=auth)
    assert bad.status_code==403


def test_web_form_updates_prompts_in_sqlite(tmp_path, monkeypatch):
    from whatsappreader import web

    store = Store(tmp_path / 'config.sqlite')
    store.initialize()
    monkeypatch.setattr(web, 'db', lambda: store)
    monkeypatch.setenv('WA_ADMIN_USER', 'admin')
    monkeypatch.setenv('WA_ADMIN_PASSWORD', 'a-long-admin-password')
    monkeypatch.setenv('WA_CSRF_TOKEN', 'a-csrf-secret')
    client = TestClient(app)
    auth = ('admin', 'a-long-admin-password')

    page = client.get('/whatsappreader/config', auth=auth)
    assert page.status_code == 200
    assert 'name="gemini_image_prompt"' in page.text
    assert 'name="gemini_text_prompt"' in page.text

    form = {'csrf': 'a-csrf-secret'}
    for key, value in store.settings().items():
        if isinstance(value, bool):
            if value:
                form[key] = 'on'
        else:
            form[key] = str(value)
    form['topic'] = 'Public transport delays'
    form['gemini_text_prompt'] = 'Evaluate message {text} for topic {topic}.'
    form['gemini_image_prompt'] = 'Leia o conteúdo da imagem e compare com {topic} e {text}.'
    response = client.post('/whatsappreader/config/fields', auth=auth, data=form)
    assert response.status_code == 200
    assert 'Settings saved' in response.text
    config = store.settings()
    assert config['topic'] == 'Public transport delays'
    assert config['gemini_text_prompt'] == form['gemini_text_prompt']
    assert config['gemini_image_prompt'] == form['gemini_image_prompt']
    with store.connect() as con:
        assert con.execute('SELECT count(*) FROM settings_history').fetchone()[0] == 1


def test_dashboard_status_polling(tmp_path, monkeypatch):
    from whatsappreader import web

    store = Store(tmp_path / 'status.sqlite')
    store.initialize()
    monkeypatch.setattr(web, 'db', lambda: store)
    monkeypatch.setenv('WA_ADMIN_USER', 'admin')
    monkeypatch.setenv('WA_ADMIN_PASSWORD', 'a-long-admin-password')
    auth = ('admin', 'a-long-admin-password')
    client = TestClient(app)

    assert client.get('/whatsappreader/status').status_code == 401
    initial = client.get('/whatsappreader/status', auth=auth)
    assert initial.status_code == 200
    assert initial.json() == {
        'running_id': None, 'running_stage': None,
        'last_id': None, 'last_status': None,
    }
    assert initial.headers['cache-control'] == 'no-store'

    run_id = store.start_run('manual', store.settings())
    monkeypatch.setattr(store, 'running', lambda: {'id': run_id, 'stage': 'WHATSAPP'})
    active = client.get('/whatsappreader/status', auth=auth).json()
    assert active['running_id'] == run_id
    assert active['running_stage'] == 'WHATSAPP'
    assert active['last_id'] == run_id
    assert active['last_status'] == 'RUNNING'

    monkeypatch.setattr(store, 'running', lambda: None)
    store.finish_run(run_id, 'SUCCESS')
    done = client.get('/whatsappreader/status', auth=auth).json()
    assert done['running_id'] is None
    assert done['last_id'] == run_id
    assert done['last_status'] == 'SUCCESS'

    html = client.get('/whatsappreader/', auth=auth).text
    assert "fetch('/whatsappreader/status'" in html
    assert 'setInterval(checkRunStatus, 2500)' in html
