from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

import pymupdf

from .config import data_dir


def now():
    return int(time.time() * 1000)


@contextmanager
def connection():
    conn = sqlite3.connect(data_dir() / 'library.sqlite3', timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    for folder in ('books', 'covers', 'attachments', 'exports'):
        (data_dir() / folder).mkdir(exist_ok=True)
    with connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS books (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL DEFAULT '',
              filename TEXT NOT NULL, pages INTEGER NOT NULL, category TEXT NOT NULL DEFAULT 'physics',
              added_at INTEGER NOT NULL, last_read_at INTEGER NOT NULL DEFAULT 0,
              page INTEGER NOT NULL DEFAULT 1, position REAL NOT NULL DEFAULT 0,
              zoom TEXT NOT NULL DEFAULT 'width', current_session TEXT, toc TEXT NOT NULL, labels TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
              title TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
              role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'complete',
              error TEXT NOT NULL DEFAULT '', context TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL,
              seq INTEGER PRIMARY KEY AUTOINCREMENT);
        ''')
        # 崩溃/关机后的部分回答保留，明确标为中断，不伪装为完成。
        db.execute("UPDATE messages SET status='interrupted', error='上次回答因程序关闭中断，可重试' WHERE status='streaming'")


def books():
    with connection() as db:
        return [dict(row) for row in db.execute('''SELECT id,title,author,filename,pages,category,added_at,
               last_read_at,page,position,zoom,current_session FROM books ORDER BY last_read_at DESC, added_at DESC''')]


def book(book_id):
    with connection() as db:
        row = db.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()
    if not row:
        raise ValueError('书籍不存在或已移出书库')
    result = dict(row)
    result['toc'] = json.loads(result['toc'])
    result['labels'] = json.loads(result['labels'])
    return result


def book_path(book_id):
    book(book_id)
    return data_dir() / 'books' / f'{book_id}.pdf'


def add_book(source, category='physics', original_name=None):
    source = Path(source)
    if not source.is_file() or source.suffix.lower() != '.pdf':
        raise ValueError('请选择 PDF 文件')
    digest = hashlib.sha256()
    with source.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    book_id = digest.hexdigest()[:32]
    with connection() as db:
        if db.execute('SELECT 1 FROM books WHERE id=?', (book_id,)).fetchone():
            return {'book': book(book_id), 'exists': True}
    with pymupdf.open(source) as doc:
        if doc.needs_pass:
            raise ValueError('此 PDF 已加密，请先保存一份可直接阅读的解密副本')
        if not len(doc):
            raise ValueError('PDF 没有页面')
        metadata = doc.metadata or {}
        filename = original_name or source.name
        title = metadata.get('title', '').strip() or Path(filename).stem
        title = title if len(title) > 3 and not title.lower().endswith(('.doc', '.indd')) else Path(filename).stem
        toc = doc.get_toc()
        labels = doc.get_page_labels()
        count = len(doc)
        cover = doc[0].get_pixmap(matrix=pymupdf.Matrix(240 / doc[0].rect.width, 240 / doc[0].rect.width))
        cover.save(data_dir() / 'covers' / f'{book_id}.png')
    destination = data_dir() / 'books' / f'{book_id}.pdf'
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    with connection() as db:
        db.execute('''INSERT OR IGNORE INTO books(id,title,author,filename,pages,category,added_at,toc,labels)
                      VALUES(?,?,?,?,?,?,?,?,?)''', (book_id, title, metadata.get('author', ''), filename, count,
                      category if category in ('math', 'physics', 'other') else 'other', now(),
                      json.dumps(toc, ensure_ascii=False), json.dumps(labels)))
    new_session(book_id)
    return {'book': book(book_id), 'exists': False}


def progress(book_id, page, position=0, zoom='width'):
    info = book(book_id)
    page = max(1, min(int(page), info['pages']))
    position = max(0, min(float(position), 1))
    if zoom not in ('width', 'page'):
        zoom = str(max(.4, min(3, float(zoom))))
    with connection() as db:
        db.execute('UPDATE books SET page=?,position=?,zoom=?,last_read_at=? WHERE id=?',
                   (page, position, zoom, now(), book_id))
    return {'page': page, 'position': position, 'zoom': zoom}


def update_book(book_id, title, category):
    if category not in ('math', 'physics', 'other') or not str(title).strip():
        raise ValueError('请输入书名并选择分类')
    with connection() as db:
        db.execute('UPDATE books SET title=?,category=? WHERE id=?', (str(title).strip()[:300], category, book_id))
    return book(book_id)


def remove_book(book_id):
    from .attachments import image_names
    book(book_id)
    with connection() as db:
        attachments = [name for r in db.execute('''SELECT context FROM messages m
                      JOIN sessions s ON s.id=m.session_id WHERE s.book_id=?''', (book_id,))
                       for name in image_names(json.loads(r[0]))]
        db.execute('DELETE FROM books WHERE id=?', (book_id,))
    for image in attachments:
        if image and Path(image).name == image:
            (data_dir() / 'attachments' / image).unlink(missing_ok=True)
    (data_dir() / 'books' / f'{book_id}.pdf').unlink(missing_ok=True)
    (data_dir() / 'covers' / f'{book_id}.png').unlink(missing_ok=True)


def sessions(book_id):
    book(book_id)
    with connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM sessions WHERE book_id=? ORDER BY updated_at DESC', (book_id,))]


def session(session_id):
    with connection() as db:
        row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    if not row:
        raise ValueError('会话不存在')
    return dict(row)


def new_session(book_id, title='学习笔记'):
    book(book_id)
    sid = uuid.uuid4().hex
    with connection() as db:
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (sid, book_id, str(title)[:120], now(), now()))
        db.execute('UPDATE books SET current_session=? WHERE id=?', (sid, book_id))
    return session(sid)


def select_session(book_id, session_id):
    if session(session_id)['book_id'] != book_id:
        raise ValueError('会话不属于当前书籍')
    with connection() as db:
        db.execute('UPDATE books SET current_session=? WHERE id=?', (session_id, book_id))
    return messages(session_id)


def rename_session(session_id, title):
    if not str(title).strip():
        raise ValueError('会话名称不能为空')
    session(session_id)
    with connection() as db:
        db.execute('UPDATE sessions SET title=? WHERE id=?', (str(title).strip()[:120], session_id))


def messages(session_id):
    session(session_id)
    with connection() as db:
        rows = [dict(row) for row in db.execute('SELECT * FROM messages WHERE session_id=? ORDER BY seq', (session_id,))]
    for row in rows:
        row['context'] = json.loads(row['context'])
    return rows


def add_message(session_id, role, content='', context=None, status='complete'):
    session(session_id)
    mid = uuid.uuid4().hex
    with connection() as db:
        db.execute('INSERT INTO messages(id,session_id,role,content,status,context,created_at) VALUES(?,?,?,?,?,?,?)',
                   (mid, session_id, role, content, status, json.dumps(context or {}, ensure_ascii=False), now()))
        db.execute('UPDATE sessions SET updated_at=? WHERE id=?', (now(), session_id))
    return mid


def update_message(message_id, content, status='streaming', error=''):
    with connection() as db:
        db.execute('UPDATE messages SET content=?,status=?,error=? WHERE id=?', (content, status, error, message_id))


def export_session(session_id):
    from .attachments import image_names
    s = session(session_id)
    b = book(s['book_id'])
    lines = [f"# {b['title']} · {s['title']}", '']
    for m in messages(session_id):
        lines += ['## ' + ('提问' if m['role'] == 'user' else '回答'), '']
        c = m['context']
        if c.get('page'):
            lines += [f"来源：PDF 第 {c['page']} 页", '']
        if c.get('selection'):
            lines += ['> ' + c['selection'].replace('\n', '\n> '), '']
        for name in image_names(c):
            lines += [f"![提问图片](attachments/{name})", '']
        lines += [m['content'], '']
        if m['status'] != 'complete':
            lines += [f"（{m.get('error') or m['status']}）", '']
    return '\n'.join(lines)
