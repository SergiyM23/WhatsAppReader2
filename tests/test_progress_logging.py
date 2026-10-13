"""User-facing progress logs must show activity during browser collection."""
from whatsappreader import browser, collector
from whatsappreader.reader import normalize


class Recorder:
    def __init__(self):
        self.messages=[]

    def info(self, message, *args):
        self.messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.messages.append(message % args if args else message)


class FakeClock:
    def __init__(self):
        self.current=0

    def monotonic(self):
        return self.current

    def sleep(self, seconds):
        self.current+=seconds


def test_wait_ready_reports_progress_when_login_takes_time(monkeypatch):
    log=Recorder()
    clock=FakeClock()
    monkeypatch.setattr(browser.time,'monotonic',clock.monotonic)
    monkeypatch.setattr(browser.time,'sleep',clock.sleep)
    session=browser.WhatsAppBrowser(driver=None,logger=log)
    monkeypatch.setattr(session,'is_authenticated',lambda:False)

    assert session.wait_ready(seconds=23) is False
    assert any('Waiting for WhatsApp Web: 10s elapsed' in m for m in log.messages)
    assert any('Waiting for WhatsApp Web: 20s elapsed' in m for m in log.messages)


def test_collection_reports_stages_and_scan_progress(monkeypatch):
    log=Recorder()
    clock=FakeClock()
    monkeypatch.setattr(collector.time,'monotonic',clock.monotonic)
    monkeypatch.setattr(collector.time,'sleep',clock.sleep)

    older={'metadata':'[19:00, 11.10.2026] A: ','text':'Old',
           'direction':'in','hasImage':False}
    newer={'metadata':'[19:05, 11.10.2026] A: ','text':'New',
           'direction':'in','hasImage':False}
    old_key=normalize(older)['key']

    class FakeDriver:
        def get(self,url):
            assert url=='https://web.whatsapp.com/'
        def quit(self):
            pass

    class FakeBrowser:
        def __init__(self,driver,logger):
            self.scrolls=0
        def wait_ready(self):
            return True
        def open_chat(self,chat):
            assert chat=='Test Group'
        def latest(self,*args):
            return 'latest'
        def read_batch(self,limit):
            return [newer] if self.scrolls==0 else [older]
        def snapshot(self):
            return {'earliest':str(self.scrolls),'latest':'latest'}
        def scroll(self,direction):
            self.scrolls+=1
            clock.sleep(12)
            return {'success':True},False

    class FakeStore:
        def get_checkpoint(self,chat):
            return {'last_message_key':old_key,'last_timestamp':normalize(older)['timestamp']}
        def save_scan(self,chat,messages,newest,run_id):
            assert len(messages)==1
            assert messages[0]['text']=='New'

    monkeypatch.setattr(collector,'create_browser',FakeDriver)
    monkeypatch.setattr(collector,'WhatsAppBrowser',FakeBrowser)

    count=collector._collect_locked(FakeStore(),1,{
        'max_scrolls':5,'batch_limit':100,
        'max_stagnant_scrolls':6,'image_max_attempts':1,
    },log,'Test Group')

    assert count==1
    for fragment in (
        'Starting Chromium', 'WhatsApp Web ready', 'Chat opened',
        'Scanning history', 'History boundary found: exact',
        'Saving messages and checkpoint', 'Closing Chromium',
    ):
        assert any(fragment in message for message in log.messages), fragment
