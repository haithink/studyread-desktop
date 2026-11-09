"""Exercise the actual Windows WebView2 shell using isolated local data."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))
import webview
import pymupdf

with tempfile.TemporaryDirectory(prefix='studyread-native-') as sandbox:
    os.environ['STUDYREAD_DATA_DIR'] = sandbox
    from studyread.server import ApplicationServer
    from studyread import store
    from main import NativeBridge
    source = Path(sandbox) / 'sample.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72,120), 'Classical mechanics - native PDF rendering')
        doc.save(source)
    server = ApplicationServer()
    book = store.add_book(source)['book']
    bridge = NativeBridge()
    window = webview.create_window('StudyRead Native Verification', server.start(), js_api=bridge,
                                   width=1240, height=850)
    bridge._window = window
    errors = []
    def verify():
        try:
            assert window.events.loaded.wait(30), 'Window did not load'
            end = time.monotonic() + 25
            while time.monotonic() < end:
                if window.evaluate_js('Boolean(window.studyread && document.querySelectorAll(".book-card").length===1)'):
                    break
                time.sleep(.1)
            else:
                raise AssertionError('App did not initialize in WebView2')
            assert window.evaluate_js('typeof window.pywebview.api.choose_files') == 'function'
            window.evaluate_js(f'window.studyread.openBook("{book["id"]}")')
            end = time.monotonic() + 25
            while time.monotonic() < end:
                if window.evaluate_js('Boolean(document.querySelector(".page canvas"))'):
                    break
                time.sleep(.1)
            else:
                details = window.evaluate_js('({loading:document.getElementById("pdf-loading").textContent, width:innerWidth, height:innerHeight, pageCount:window.studyread?.viewer.pagesCount, doc:!!window.studyread?.state.doc})')
                raise AssertionError('Native PDF canvas did not render: ' + str(details))
            print('NATIVE PASS: WebView2, library, PDF canvas, native bridge', flush=True)
        except BaseException as exc:
            errors.append(str(exc))
        finally:
            window.destroy()
    try:
        webview.start(verify, gui='edgechromium', storage_path=str(Path(sandbox)/'webview'),
                      icon=str(repo/'studyread/web/icon.ico'))
    finally:
        server.close()
    if errors:
        raise AssertionError(errors)
