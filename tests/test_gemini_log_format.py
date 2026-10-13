"""One concise, identifying log line per successfully analyzed Gemini message."""
from whatsappreader import gemini


class Recorder:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, text, *args):
        self.infos.append(text % args if args else text)

    def warning(self, text, *args):
        self.warnings.append(text % args if args else text)


class Store:
    def __init__(self, messages):
        self.messages = messages
        self.results = []

    def pending(self):
        return self.messages

    def analyze(self, key, run_id, status, result=None, error=None):
        self.results.append((key, status))


def config():
    return {
        'topic': 'casting', 'gemini_max_attempts': 3,
        'gemini_requests_per_minute': 20,
        'gemini_rate_limit_wait_seconds': 0,
        'gemini_inter_request_delay_seconds': 0,
        'retry_delay_seconds': 0,
        'relevance_threshold': 70,
    }


def sample(key='a' * 64):
    return {
        'key': key,
        'message_date': '13.10.2026',
        'message_time': '15:05',
        'author': 'Test Sender',
        'text': 'Test casting message',
        'direction': 'in',
        'has_image': False,
    }


def test_success_logs_one_concise_line_without_hash(monkeypatch):
    messages = [sample('a'*64), sample('b'*64)]
    answers = iter([
        {'relevant': False, 'score': 65},
        {'relevant': True, 'score': 90},
    ])
    monkeypatch.setattr(gemini, 'classify', lambda *a: next(answers))
    store, logger = Store(messages), Recorder()

    result = gemini.analyze_pending(store, 3, config(), logger)

    assert result == {'processed': 2, 'relevant': 1, 'blocked': 0}
    lines = [line for line in logger.infos if line.startswith('[')]
    assert lines == [
        '[1/2] 13.10.2026 15:05 | Test Sender -> not_relevant, score 65',
        '[2/2] 13.10.2026 15:05 | Test Sender -> relevant, score 90',
    ]
    assert not any('Gemini analyzing message' in x for x in logger.infos)
    assert not any(messages[0]['key'] in x for x in logger.infos)


def test_retry_keeps_error_warning_but_only_one_success_line(monkeypatch):
    attempts = iter([RuntimeError('Temporary Gemini failure'),
                     {'relevant': False, 'score': 10}])

    def classify(*args):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gemini, 'classify', classify)
    monkeypatch.setattr(gemini.time, 'sleep', lambda _: None)
    store, logger = Store([sample()]), Recorder()

    gemini.analyze_pending(store, 3, config(), logger)

    assert [line for line in logger.infos if line.startswith('[')] == [
        '[1/1] 13.10.2026 15:05 | Test Sender -> not_relevant, score 10',
    ]
    assert len(logger.warnings) == 1
    assert 'attempt 1/3 failed' in logger.warnings[0]
