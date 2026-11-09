import threading
import time
import uuid

from . import config, context, llm, store
from .attachments import decode_images, image_names, save_images


class ChatService:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.RLock()

    def active(self, session_id):
        with self.lock:
            return next((j for j in self.jobs.values() if j['session'] == session_id and j['status'] == 'streaming'), None)

    def ask(self, session_id, question, page, selection='', rect=None, attach_image=False, images=None):
        with self.lock:
            if self.active(session_id):
                raise ValueError('此会话正在回答，请等待完成或先停止')
            question = str(question).strip()
            if not question and images:
                question = '请解释图片中的内容，结合当前阅读上下文说明。'
            if not question or len(question) > 12000:
                raise ValueError('请输入问题，最多 12000 字')
            profile = dict(config.profile())
            if (attach_image or rect or images) and not profile.get('vision'):
                raise ValueError('公式和图示截图需要支持图片的模型，请在模型设置中启用图片能力；文字问题可直接发送')
            pasted = decode_images(images)
            session = store.session(session_id)
            ctx = context.extract(session['book_id'], page, selection, rect, bool(attach_image or rect))
            if pasted:
                ctx['images'] = save_images(pasted)
            store.add_message(session_id, 'user', question, ctx)
            if len(store.messages(session_id)) == 1:
                store.rename_session(session_id, question[:36])
            return self._start(session_id, profile)

    def retry(self, session_id, message_id):
        with self.lock:
            if self.active(session_id):
                raise ValueError('此会话正在回答')
            rows = store.messages(session_id)
            if not rows or rows[-1]['id'] != message_id or rows[-1]['role'] != 'assistant':
                raise ValueError('只能重试本会话最后一条回答；其他问题请继续追问')
            if rows[-1]['status'] == 'complete':
                raise ValueError('回答已完成，请继续追问')
            profile = dict(config.profile())
            prior = rows[-2] if len(rows) > 1 else None
            if prior and image_names(prior['context']) and not profile.get('vision'):
                raise ValueError('这条问题含图片，请选择支持图片的模型')
            return self._start(session_id, profile, message_id)

    def _start(self, session_id, profile, assistant_id=None):
        messages, stats = context.conversation(session_id, profile, assistant_id)
        if assistant_id:
            store.update_message(assistant_id, '', 'streaming')
        else:
            assistant_id = store.add_message(session_id, 'assistant', status='streaming')
        jid = uuid.uuid4().hex
        job = {'id': jid, 'session': session_id, 'messageId': assistant_id, 'text': '', 'status': 'streaming',
               'error': '', 'cancel': threading.Event(), 'responses': [], 'stats': stats, 'model': profile['model']}
        self.jobs[jid] = job
        threading.Thread(target=self._run, args=(job, profile, messages), daemon=True).start()
        return self.public(job)

    def _run(self, job, profile, messages):
        last_save = 0
        def delta(text):
            nonlocal last_save
            if job['cancel'].is_set():
                raise llm.Cancelled()
            with self.lock:
                job['text'] += text
            if time.monotonic() - last_save > .5:
                store.update_message(job['messageId'], job['text'])
                last_save = time.monotonic()
        status, error = 'complete', ''
        try:
            llm.stream(profile, context.SYSTEM, messages, delta, job['cancel'], job['responses'])
        except llm.Cancelled:
            status, error = 'cancelled', '已停止，部分回答已保存'
        except (llm.ModelError, ValueError) as exc:
            status, error = 'error', str(exc)
        except Exception:
            status, error = 'error', '回答生成异常，已有内容已保存，可重试'
        finally:
            # 先落盘再通知前端完成，刷新/重开会话不会丢掉最后一段。
            store.update_message(job['messageId'], job['text'], status, error)
            with self.lock:
                job.update(status=status, error=error)
                # 只保留少量近期任务；会话全文以数据库为准。
                completed = [k for k, v in self.jobs.items() if v['status'] != 'streaming']
                for key in completed[:-24]:
                    self.jobs.pop(key, None)

    @staticmethod
    def public(job):
        return {k: v for k, v in job.items() if k not in ('cancel', 'responses')}

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError('生成任务已结束，请刷新会话')
            return self.public(self.jobs[job_id])

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job['cancel'].set()
            # close 从另一个线程中断正在读取的 SSE；界面可立刻继续阅读。
            for response in job['responses']:
                threading.Thread(target=response.close, daemon=True).start()

    def close(self):
        with self.lock:
            ids = [j['id'] for j in self.jobs.values() if j['status'] == 'streaming']
        for jid in ids:
            self.cancel(jid)
