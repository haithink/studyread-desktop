"""Isolated app and local mock model; never uses personal settings or API keys."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf

temporary = tempfile.TemporaryDirectory(prefix='studyread-browser-')
os.environ['STUDYREAD_DATA_DIR'] = temporary.name
from studyread import config, store, llm
from studyread.server import ApplicationServer

app = ApplicationServer()
source = os.environ.get('STUDYREAD_SAMPLE_PDF')
if not source:
    source = str(Path(temporary.name) / 'Mechanics.pdf')
    with pymupdf.open() as doc:
        for i in range(8):
            # A smaller cover must not determine fit-width for textbook pages.
            p = doc.new_page(width=235 if i == 0 else 520,height=336 if i == 0 else 720)
            p.insert_text((60,80),f'Chapter {i+1}: Classical Mechanics',fontsize=20)
            p.insert_text((60,160),'Newtonian mechanics begins with a particle.\nThe force equals mass times acceleration.\nF = m a',fontsize=13)
            p.insert_text((60,260),'Why is acceleration proportional to force?',fontsize=12)
        doc.set_metadata({'title':'Classical Mechanics - Test Edition','author':'Test author'})
        doc.set_toc([[1,'Chapter 1: Newtonian mechanics',1],[2,'1.1 Force and motion',2],[1,'Chapter 2: Energy',4]])
        doc.save(source)
book = store.add_book(source)['book']
config.save_settings({'profiles':[{'id':'test-model','name':'Local test model','baseUrl':'http://127.0.0.1:9',
                                  'apiKey':'test-only','provider':'openai','model':'test-model','vision':True}],
                      'activeProfile':'test-model'})
def fake(profile, system, messages, delta, cancel, responses):
    text = r'''从牛顿第二定律开始：

$$F = ma = m\frac{dv}{dt}$$

在质量 $m$ 不变时，力描述动量的变化率。把加速度代入，可以逐步得到这个关系。

1. 明确研究对象和参考系。
2. 写出合外力，注意正方向。
3. 结合初始条件求解。

此前会话中已有 %d 条消息；本轮引用与推导将保存在同一会话。''' % len(messages)
    for i in range(0,len(text),30):
        if cancel.is_set():
            raise llm.Cancelled()
        delta(text[i:i+30]);time.sleep(.12)
llm.stream = fake
app.start()
print(json.dumps({'url':app.url,'book':book['id'],'data':temporary.name}),flush=True)
try:
    threading.Event().wait()
except KeyboardInterrupt:
    pass
finally:
    app.close();temporary.cleanup()
