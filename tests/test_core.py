import base64
import io
import json
from pathlib import Path
import threading
import time
import zipfile

import pymupdf
import pytest
import requests

from studyread import config, context, llm, store, attachments
from studyread.chat import ChatService
from studyread.server import ApplicationServer, export_zip


def until(fn, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError('Timed out')


def test_import_duplicate_cover_original_preserved(textbook, tmp_path):
    source = tmp_path / 'Mechanics.pdf'
    before = source.read_bytes()
    duplicate = store.add_book(source)
    assert duplicate['exists'] and duplicate['book']['id'] == textbook['id']
    assert len(store.books()) == 1 and source.read_bytes() == before
    assert (config.data_dir() / 'covers' / (textbook['id'] + '.png')).stat().st_size > 100
    assert len(textbook['toc']) == 3 and textbook['pages'] == 5
    assert len(store.sessions(textbook['id'])) == 1


def test_reading_position_and_sessions(textbook):
    bid = textbook['id']
    store.progress(bid, 4, .43, '1.25')
    saved = store.book(bid)
    assert saved['page'] == 4 and saved['position'] == .43 and saved['zoom'] == '1.25'
    first = saved['current_session']
    second = store.new_session(bid, 'Energy and forces')['id']
    store.add_message(first, 'user', 'First topic')
    store.add_message(second, 'user', 'Second topic')
    store.select_session(bid, first)
    assert store.book(bid)['current_session'] == first
    assert store.messages(first)[0]['content'] == 'First topic'
    assert store.messages(second)[0]['content'] == 'Second topic'
    assert store.progress(bid, 100, 1.5)['page'] == 5


def test_context_page_and_formula_image(textbook):
    ctx = context.extract(textbook['id'], 3, 'F = m a', [.05, .12, .9, .37], True)
    assert ctx['page'] == 3 and 'F = m a' in ctx['selection']
    assert 'Page 3 states' in ctx['nearby'] and 'Page 2 states' in ctx['nearby'] and 'Page 4 states' in ctx['nearby']
    assert 'Page 1 states' not in ctx['nearby'] and 'Page 5 states' not in ctx['nearby']
    image = config.data_dir() / 'attachments' / ctx['image']
    assert image.read_bytes().startswith(b'\x89PNG')
    with pymupdf.open(image) as doc:
        assert doc[0].rect.width > 300 and doc[0].rect.height > 100
    for rect in ([.9, .1, .1, .2], [float('nan'), 0, 1, 1], [0, 0, 2, 1]):
        with pytest.raises(ValueError):
            context.extract(textbook['id'], 2, rect=rect)


def test_context_budget_preserves_full_history(textbook, model):
    sid = textbook['current_session']
    for i in range(8):
        store.add_message(sid, 'user', f'Question {i}', {'page': i % 5 + 1, 'bookTitle': 'Mechanics',
                                                     'selection': '', 'nearby': 'text ' * 1400})
        store.add_message(sid, 'assistant', f'Answer {i}')
    messages, stats = context.conversation(sid, model)
    assert stats['historyTurns'] < stats['totalTurns'] == 8
    assert stats['contextChars'] <= 42000 and messages[-1]['text'] == 'Answer 7'
    assert len(messages) % 2 == 0 and messages[0]['role'] == 'user'
    assert len(store.messages(sid)) == 16


def test_questions_continue_previous_derivation(textbook, model, monkeypatch):
    seen = []
    def fake(profile, system, messages, on_delta, cancel, response_holder):
        seen.append(messages)
        on_delta('由牛顿第二定律，')
        on_delta('$$F=ma$$。')
    monkeypatch.setattr(llm, 'stream', fake)
    chat = ChatService()
    sid = textbook['current_session']
    first = chat.ask(sid, 'Explain force', 2, 'F = m a')
    until(lambda: chat.get(first['id'])['status'] == 'complete')
    second = chat.ask(sid, 'How does the previous result change?', 4)
    until(lambda: chat.get(second['id'])['status'] == 'complete')
    assert len(store.messages(sid)) == 4
    assert len(seen[1]) == 3 and '$$F=ma$$' in seen[1][1]['text']
    assert 'PDF 第 2 页' in seen[1][0]['text'] and 'PDF 第 4 页' in seen[1][-1]['text']


def test_duplicate_generation_cancel_and_retry(textbook, model, monkeypatch):
    entered = threading.Event()
    def fake(profile, system, messages, on_delta, cancel, responses):
        on_delta('Partial derivation')
        entered.set()
        cancel.wait(3)
        if cancel.is_set():
            raise llm.Cancelled()
    monkeypatch.setattr(llm, 'stream', fake)
    sid = textbook['current_session']
    chat = ChatService()
    job = chat.ask(sid, 'Derive this formula', 2)
    assert entered.wait(2)
    with pytest.raises(ValueError):
        chat.ask(sid, 'Duplicate', 2)
    assert len(store.messages(sid)) == 2
    chat.cancel(job['id'])
    until(lambda: chat.get(job['id'])['status'] == 'cancelled')
    assert store.messages(sid)[-1]['content'] == 'Partial derivation'
    monkeypatch.setattr(llm, 'stream', lambda p, s, m, delta, c, r: delta('Finished derivation'))
    again = chat.retry(sid, job['messageId'])
    until(lambda: chat.get(again['id'])['status'] == 'complete')
    assert len(store.messages(sid)) == 2 and store.messages(sid)[-1]['content'] == 'Finished derivation'


def test_restart_marks_partial_interrupted(textbook):
    sid = textbook['current_session']
    store.add_message(sid, 'user', 'Continue')
    store.add_message(sid, 'assistant', 'Partial response', status='streaming')
    store.initialize()
    assert store.messages(sid)[-1]['status'] == 'interrupted'
    assert store.messages(sid)[-1]['content'] == 'Partial response'


def test_text_only_model_rejects_image_before_saving_question(textbook, model):
    current = config.settings()
    current['profiles'][0]['vision'] = False
    config.save_settings(current)
    with pytest.raises(ValueError, match='图片'):
        ChatService().ask(textbook['current_session'], 'Explain formula', 2, rect=[.1,.1,.5,.5])
    assert not store.messages(textbook['current_session'])


def test_profile_masks_key_and_keeps_blank_update(model):
    public = config.public_settings()
    assert 'test-only-key' not in json.dumps(public) and public['profiles'][0]['hasKey']
    public['profiles'][0]['apiKey'] = ''
    config.save_settings(public)
    assert config.profile()['apiKey'] == 'test-only-key'
    assert llm.endpoint(model) == 'http://127.0.0.1:9/v1/chat/completions'
    assert llm.endpoint(dict(model, provider='anthropic', baseUrl='https://example.invalid/v1')) == 'https://example.invalid/v1/messages'


def test_both_provider_image_payloads(textbook, model):
    ctx = context.extract(textbook['id'], 2, rect=[.05,.12,.9,.4], attach_image=True)
    messages = [{'role':'user','text':'Formula?', 'image':ctx['image']}]
    body = llm.payload(model, 'teacher', messages)
    assert body['messages'][0]['role'] == 'system'
    assert body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    anthropic = llm.payload(dict(model, provider='anthropic'), 'teacher', messages)
    assert anthropic['system'] == 'teacher'
    assert anthropic['messages'][0]['content'][0]['source']['media_type'] == 'image/png'


def clipboard_png(textbook):
    with pymupdf.open(store.book_path(textbook['id'])) as doc:
        raw = doc[1].get_pixmap(matrix=pymupdf.Matrix(.5, .5)).tobytes('png')
    return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_pasted_images_chat_retry_export_and_cleanup(textbook, model, monkeypatch, provider):
    seen = []
    def fake(profile, system, messages, delta, cancel, responses):
        seen.append(llm.payload(dict(profile, provider=provider), system, messages))
        if len(seen) == 1:
            raise llm.ModelError('Temporary test failure')
        delta('图片中的公式是 $$F=ma$$。')
    monkeypatch.setattr(llm, 'stream', fake)
    sid = textbook['current_session']
    chat = ChatService()
    job = chat.ask(sid, '', 2, attach_image=True, images=[clipboard_png(textbook)] * 2)
    until(lambda: chat.get(job['id'])['status'] == 'error')
    rows = store.messages(sid)
    assert rows[0]['content'].startswith('请解释图片')
    names = attachments.image_names(rows[0]['context'])
    assert len(names) == 3
    blocks = seen[0]['messages'][-1]['content']
    assert len(blocks) == 4
    assert sum(b['type'] == ('image' if provider == 'anthropic' else 'image_url') for b in blocks) == 3
    again = chat.retry(sid, job['messageId'])
    until(lambda: chat.get(again['id'])['status'] == 'complete')
    assert len(store.messages(sid)) == 2 and seen[1]['messages'][-1]['content'] == blocks
    with zipfile.ZipFile(io.BytesIO(export_zip(sid))) as archive:
        for name in names:
            assert archive.read('attachments/' + name).startswith(b'\x89PNG')
            assert name in archive.read('conversation.md').decode()
    followup = chat.ask(sid, '图片中的第二个符号是什么意思？', 3)
    until(lambda: chat.get(followup['id'])['status'] == 'complete')
    assert len(seen[-1]['messages'][-3]['content']) == 4
    assert isinstance(seen[-1]['messages'][-1]['content'], str)
    # A new service instance still sees the saved image references and answer.
    assert len(attachments.image_names(store.messages(sid)[0]['context'])) == 3
    store.remove_book(textbook['id'])
    assert all(not (config.data_dir() / 'attachments' / name).exists() for name in names)


def test_invalid_pasted_images_leave_no_question_or_files(textbook, model):
    good = clipboard_png(textbook)
    bad = 'data:image/png;base64,' + base64.b64encode(b'not a PNG').decode()
    for values in ([good, bad], [good] * 5, ['file:///private.png'], 'not a list'):
        with pytest.raises(ValueError):
            ChatService().ask(textbook['current_session'], 'Explain', 2, images=values)
    assert not store.messages(textbook['current_session'])
    assert not list((config.data_dir() / 'attachments').iterdir())


def test_text_model_rejects_pasted_image_and_image_retry(textbook, model, monkeypatch):
    monkeypatch.setattr(llm, 'stream', lambda *args: (_ for _ in ()).throw(llm.ModelError('Failure')))
    chat = ChatService()
    sid = textbook['current_session']
    job = chat.ask(sid, 'Explain', 2, images=[clipboard_png(textbook)])
    until(lambda: chat.get(job['id'])['status'] == 'error')
    settings = config.settings()
    settings['profiles'][0]['vision'] = False
    config.save_settings(settings)
    with pytest.raises(ValueError, match='图片'):
        chat.retry(sid, job['messageId'])
    with pytest.raises(ValueError, match='图片'):
        chat.ask(sid, 'Another image', 2, images=[clipboard_png(textbook)])
    assert len(store.messages(sid)) == 2


def test_export_contains_saved_quotes_latex_and_images(textbook):
    sid = textbook['current_session']
    ctx = context.extract(textbook['id'], 2, rect=[.05,.12,.9,.4], attach_image=True)
    store.add_message(sid, 'user', 'Derive this', ctx)
    store.add_message(sid, 'assistant', '$$F=ma$$')
    with zipfile.ZipFile(io.BytesIO(export_zip(sid))) as archive:
        text = archive.read('conversation.md').decode('utf-8')
        assert '$$F=ma$$' in text and 'PDF 第 2 页' in text
        assert 'attachments/' + ctx['image'] in archive.namelist()


def test_remove_managed_copy_only(textbook, tmp_path):
    source = tmp_path / 'Mechanics.pdf'
    managed = store.book_path(textbook['id'])
    ctx = context.extract(textbook['id'], 1, attach_image=True)
    store.add_message(textbook['current_session'], 'user', 'Why?', ctx)
    store.remove_book(textbook['id'])
    assert source.exists() and not managed.exists() and not store.books()
    assert not (config.data_dir() / 'attachments' / ctx['image']).exists()


def test_http_range_and_origin_protection(textbook):
    app = ApplicationServer()
    url = app.start()
    try:
        response = requests.get(url + 'pdf/' + textbook['id'] + '.pdf', headers={'Range':'bytes=10-49'})
        original = store.book_path(textbook['id']).read_bytes()
        assert response.status_code == 206 and response.content == original[10:50]
        assert response.headers['Content-Range'] == f'bytes 10-49/{len(original)}'
        assert requests.get(url+'pdf/'+textbook['id']+'.pdf',headers={'Range':'bytes=99999999-'}).status_code == 416
        assert requests.get(app.origin + '/wrong/api/bootstrap').status_code == 403
        assert requests.post(url+'api/progress',json={'bookId':textbook['id'],'page':3}).status_code == 403
        assert requests.post(url+'api/progress',json={'bookId':textbook['id'],'page':3},
                             headers={'X-StudyRead':app.token,'Origin':'https://evil.invalid'}).status_code == 403
        assert requests.get(url+'%2e%2e/settings.json').status_code == 403
        data = requests.get(url+'api/bootstrap').json()
        assert len(data['books']) == 1
    finally:
        app.close()


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_real_http_sse_unicode_and_history(model, provider):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if provider == 'anthropic':
                events = [{'type':'content_block_delta','delta':{'text':'由牛顿定律'}},
                          {'type':'content_block_delta','delta':{'text':'，$$F=ma$$。'}}, {'type':'message_stop'}]
            else:
                events = [{'choices':[{'delta':{'content':'由牛顿定律'}}]},
                          {'choices':[{'delta':{'content':'，$$F=ma$$。'}}]}, {'choices':[{'finish_reason':'stop','delta':{}}]}]
            body = ''.join('data: '+json.dumps(e,ensure_ascii=False)+'\n\n' for e in events).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        chunks=[]
        llm.stream(dict(model, provider=provider, baseUrl=f'http://127.0.0.1:{server.server_port}'), 'teacher',
                   [{'role':'user','text':'First question'},{'role':'assistant','text':'First answer'},
                    {'role':'user','text':'Follow up'}],chunks.append,threading.Event())
        assert ''.join(chunks) == '由牛顿定律，$$F=ma$$。'
        assert received[0]['messages'][-1]['content'] == 'Follow up'
        assert len(received[0]['messages']) == (3 if provider == 'anthropic' else 4)
    finally:
        server.shutdown();server.server_close()
