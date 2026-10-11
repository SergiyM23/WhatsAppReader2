from whatsappreader.reader import normalize,chronological,boundary,new_since


def msg(text,time='12:00',date='10.10.2026'):
    return normalize({'metadata':f'[{time}, {date}] Test: ','text':text,'direction':'in','hasImage':False})

def test_legacy_key_uses_boolean_text_and_first_256_chars():
    import hashlib
    message=msg('hello')
    assert message['key']==hashlib.sha256('[12:00, 10.10.2026] Test:|in|False|hello'.encode()).hexdigest()

def test_first_run_initializes_baseline_only():
    messages=[msg('old'),msg('latest','12:01')]
    assert boundary(messages,None)=='baseline'
    assert new_since(messages,None,'baseline')==[]

def test_exact_checkpoint_excludes_previous_and_returns_new():
    old=msg('old');fresh=msg('new','12:01')
    cp={'last_message_key':old['key'],'last_timestamp':old['timestamp']}
    assert boundary([old,fresh],cp)=='exact'
    assert new_since([old,fresh],cp,'exact')==[fresh]

def test_deleted_checkpoint_timestamp_fallback_includes_same_minute():
    older=msg('older','11:59');same=msg('same','12:00');latest=msg('latest','12:01')
    cp={'last_message_key':'deleted','last_timestamp':same['timestamp']}
    assert boundary([older,same,latest],cp)=='timestamp'
    assert new_since([older,same,latest],cp,'timestamp')==[same,latest]

def test_chronological_deduplication():
    a=msg('a');b=msg('b','12:01');c=msg('c','12:02')
    assert chronological([[b,c],[a,b]])==[a,b,c]

def test_bounded_window():
    m=msg('a')
    assert new_since([m],{'last_message_key':'not-found'},'bounded')==[m]
