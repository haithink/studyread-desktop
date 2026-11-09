import io
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import tempfile
import threading
from urllib.parse import parse_qs, unquote, urlparse
import zipfile

from . import __version__, config, store
from .chat import ChatService


def export_zip(session_id):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('conversation.md', store.export_session(session_id))
        for message in store.messages(session_id):
            name = message['context'].get('image')
            if name and Path(name).name == name:
                source = config.data_dir() / 'attachments' / name
                if source.is_file():
                    archive.write(source, 'attachments/' + name)
    return output.getvalue()


class ApplicationServer:
    def __init__(self):
        store.initialize()
        self.chat = ChatService()
        self.token = secrets.token_urlsafe(32)
        self.web = Path(__file__).resolve().parent / 'web'
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self.http.daemon_threads = True
        self.origin = f'http://127.0.0.1:{self.http.server_port}'
        self.url = f'{self.origin}/{self.token}/'

    def start(self):
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        return self.url

    def close(self):
        self.chat.close()
        self.http.shutdown()
        self.http.server_close()

    def dispatch(self, method, path, data, query):
        if method == 'GET':
            if path == 'bootstrap':
                return {'version': __version__, 'books': store.books(), 'settings': config.public_settings()}
            if path == 'book':
                info = store.book(query['id'][0])
                info['sessions'] = store.sessions(info['id'])
                return info
            if path == 'messages':
                sid = query['session'][0]
                active = self.chat.active(sid)
                return {'messages': store.messages(sid), 'active': self.chat.public(active) if active else None}
            if path == 'job':
                return self.chat.get(query['id'][0])
        if method == 'POST':
            if path == 'import':
                if not isinstance(data.get('paths'), list) or len(data['paths']) > 100:
                    raise ValueError('请选择要导入的 PDF 文件')
                results = []
                for source in data['paths']:
                    try:
                        results.append(store.add_book(source, data.get('category', 'physics')))
                    except (ValueError, OSError, RuntimeError):
                        results.append({'error': '导入失败：请选择未加密、未损坏的 PDF', 'filename': Path(source).name})
                return results
            if path == 'progress':
                return store.progress(data['bookId'], data['page'], data.get('position', 0), data.get('zoom', 'width'))
            if path == 'book/update':
                return store.update_book(data['id'], data['title'], data['category'])
            if path == 'book/remove':
                # 正在回答的书籍先停止生成，再移除，避免数据库写入悬空记录。
                if any(self.chat.active(s['id']) for s in store.sessions(data['id'])):
                    raise ValueError('这本书仍有回答正在生成，请先停止后再移除')
                store.remove_book(data['id'])
                return {'ok': True}
            if path == 'session/new':
                return store.new_session(data['bookId'], data.get('title', '学习笔记'))
            if path == 'session/select':
                return store.select_session(data['bookId'], data['sessionId'])
            if path == 'session/rename':
                store.rename_session(data['sessionId'], data['title'])
                return {'ok': True}
            if path == 'ask':
                return self.chat.ask(data['sessionId'], data['question'], data['page'],
                                     data.get('selection', ''), data.get('rect'), data.get('attachImage', False))
            if path == 'retry':
                return self.chat.retry(data['sessionId'], data['messageId'])
            if path == 'cancel':
                self.chat.cancel(data['id'])
                return {'ok': True}
            if path == 'settings':
                return config.save_settings(data)
            if path == 'settings/import':
                return config.import_kandu()
            if path == 'settings/test':
                from . import llm
                profile = config.profile()
                parts = []
                llm.stream(profile, 'You are a connection test assistant.',
                           [{'role': 'user', 'text': 'Reply only: OK'}], parts.append, threading.Event())
                return {'reply': ''.join(parts)[:100]}
        raise ValueError('找不到此操作')

    def _handler(self):
        app = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def handle(self):
                try:
                    super().handle()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    pass

            def log_message(self, *args):
                pass

            def reply(self, body=b'', status=200, mime='application/json; charset=utf-8', extra=None):
                if not isinstance(body, bytes):
                    body = json.dumps(body, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; worker-src 'self' blob:; connect-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
                for k, v in (extra or {}).items():
                    self.send_header(k, str(v))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            def route(self):
                parsed = urlparse(self.path)
                if self.headers.get('Host') != f'127.0.0.1:{app.http.server_port}' or not parsed.path.startswith('/' + app.token + '/'):
                    self.reply({'error': '访问链接已失效'}, 403)
                    return
                relative = unquote(parsed.path[len(app.token) + 2:])
                query = parse_qs(parsed.query)
                if self.command == 'POST':
                    if self.headers.get('X-StudyRead') != app.token or self.headers.get('Origin', app.origin) != app.origin:
                        self.reply({'error': '请求来源无效'}, 403)
                        return
                    length = int(self.headers.get('Content-Length', 0))
                    if relative == 'api/upload':
                        if not 0 < length <= 1024 * 1024 * 1024:
                            raise ValueError('文件大小超出限制（最大 1GB）')
                        name = Path(unquote(self.headers.get('X-Filename', 'book.pdf'))).name
                        if not name.lower().endswith('.pdf'):
                            raise ValueError('只支持 PDF 文件')
                        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as upload:
                            temporary = Path(upload.name)
                            try:
                                remaining = length
                                while remaining:
                                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                                    if not chunk:
                                        raise ValueError('文件上传中断')
                                    upload.write(chunk)
                                    remaining -= len(chunk)
                                upload.close()
                                result = store.add_book(temporary, query.get('category', ['physics'])[0], name)
                            finally:
                                upload.close()
                                temporary.unlink(missing_ok=True)
                        self.reply(result)
                        return
                    if length > 1024 * 1024:
                        raise ValueError('请求内容过大')
                    data = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
                else:
                    data = {}
                if relative.startswith('api/'):
                    if relative == 'api/export' and self.command == 'GET':
                        self.reply(export_zip(query['session'][0]), mime='application/zip',
                                   extra={'Content-Disposition': 'attachment; filename="StudyRead-conversation.zip"'})
                    else:
                        self.reply(app.dispatch(self.command, relative[4:], data, query))
                    return
                if self.command not in ('GET', 'HEAD'):
                    self.reply({'error': '不支持的请求方法'}, 405)
                    return
                if relative.startswith('pdf/'):
                    bid = relative[4:].removesuffix('.pdf')
                    self.pdf(store.book_path(bid))
                    return
                if relative.startswith(('covers/', 'attachments/')):
                    kind, name = relative.split('/', 1)
                    if not re.fullmatch(r'[a-f0-9]{32}\.png', name):
                        raise ValueError('无效图片')
                    path = config.data_dir() / kind / name
                else:
                    path = (app.web / (relative or 'index.html')).resolve()
                    if not path.is_relative_to(app.web.resolve()):
                        self.reply({'error': '无效路径'}, 403)
                        return
                if not path.is_file():
                    self.reply({'error': '文件不存在'}, 404)
                    return
                mime = {'.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css',
                        '.wasm': 'application/wasm'}.get(path.suffix) or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                self.reply(path.read_bytes(), mime=mime)

            def pdf(self, path):
                size = path.stat().st_size
                value = self.headers.get('Range')
                start, end, status = 0, size - 1, 200
                if value:
                    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
                    if not match or not any(match.groups()):
                        self.reply(b'', 416, extra={'Content-Range': f'bytes */{size}'})
                        return
                    left, right = match.groups()
                    start = int(left) if left else max(0, size - int(right))
                    end = min(size - 1, int(right)) if left and right else size - 1
                    if start > end or start >= size:
                        self.reply(b'', 416, extra={'Content-Range': f'bytes */{size}'})
                        return
                    status = 206
                self.send_response(status)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Cache-Control', 'private, max-age=600')
                self.send_header('Referrer-Policy', 'no-referrer')
                if status == 206:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                if self.command == 'HEAD':
                    return
                with path.open('rb') as file:
                    file.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = file.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def do_HEAD(self):
                self.handle_request()

            def handle_request(self):
                try:
                    self.route()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    self.reply({'error': str(exc) if isinstance(exc, ValueError) else '请求参数无效'}, 400)
                except Exception:
                    self.reply({'error': '操作失败，请检查文件或设置后重试'}, 500)
        return Handler
