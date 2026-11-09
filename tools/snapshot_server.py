"""Read-only snapshot of actual local reading data; never copies API settings."""
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import json

repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo))
personal=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'StudyRead'
with tempfile.TemporaryDirectory(prefix='studyread-snapshot-') as temp:
    root=Path(temp)
    source=sqlite3.connect((personal/'library.sqlite3').as_uri()+'?mode=ro',uri=True)
    target=sqlite3.connect(root/'library.sqlite3')
    source.backup(target);source.close();target.close()
    for name in ('covers','attachments'):
        if (personal/name).is_dir():
            shutil.copytree(personal/name,root/name)
    (root/'books').mkdir()
    for source in (personal/'books').glob('*.pdf'):
        os.link(source,root/'books'/source.name)
    os.environ['STUDYREAD_DATA_DIR']=str(root)
    from studyread.server import ApplicationServer
    app=ApplicationServer()
    print(json.dumps({'url':app.start(),'data':temp}),flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
