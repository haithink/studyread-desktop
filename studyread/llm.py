import base64
import json
import re
import threading

import requests

from .config import data_dir
from .attachments import image_names


class ModelError(Exception):
    pass


class Cancelled(Exception):
    pass


def endpoint(profile):
    base = profile['baseUrl'].rstrip('/')
    suffix = '/messages' if profile.get('provider') == 'anthropic' else '/chat/completions'
    if base.endswith(suffix):
        return base
    return base + ('' if re.search(r'/v\d+$', base) else '/v1') + suffix


def payload(profile, system, messages):
    anthropic = profile.get('provider') == 'anthropic'
    out = []
    for m in messages:
        images = image_names(m)
        content = m['text']
        if images:
            if not profile.get('vision'):
                raise ModelError('当前模型未启用图片能力，请在设置中选择支持图片的模型')
            blocks = []
            for image in images:
                if image != __import__('pathlib').Path(image).name:
                    raise ModelError('图片路径无效')
                b64 = base64.b64encode((data_dir() / 'attachments' / image).read_bytes()).decode('ascii')
                blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': b64}}
                              if anthropic else {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + b64}})
            text = {'type': 'text', 'text': m['text']}
            content = blocks + [text] if anthropic else [text] + blocks
        out.append({'role': m['role'], 'content': content})
    body = {'model': profile['model'], 'messages': out, 'stream': True, 'max_tokens': 8000}
    if anthropic:
        body['system'] = system
    else:
        body['messages'].insert(0, {'role': 'system', 'content': system})
    return body


def stream(profile, system, messages, on_delta, cancel, response_holder=None):
    anthropic = profile.get('provider') == 'anthropic'
    headers = {'x-api-key': profile['apiKey'], 'anthropic-version': '2023-06-01'} if anthropic else {
        'Authorization': 'Bearer ' + profile['apiKey']}
    headers['Accept'] = 'text/event-stream'
    if cancel.is_set():
        raise Cancelled()
    try:
        with requests.post(endpoint(profile), json=payload(profile, system, messages), headers=headers,
                           stream=True, timeout=(15, 90)) as response:
            if response_holder is not None:
                response_holder.append(response)
            if response.status_code != 200:
                # 不把密钥或请求体写入错误日志。
                messages_by_code = {401: '密钥无效', 403: '接口拒绝访问', 429: '请求过于频繁或余额不足',
                                    404: 'API 地址或模型不存在', 400: '请求被拒绝，请检查模型是否支持图片及参数'}
                raise ModelError(f"HTTP {response.status_code}：{messages_by_code.get(response.status_code, '模型服务请求失败')}")
            if 'json' in response.headers.get('Content-Type', '').lower():
                data = response.json()
                if anthropic:
                    text = ''.join(b.get('text', '') for b in data.get('content', []) if isinstance(b, dict))
                    cut = data.get('stop_reason') == 'max_tokens'
                else:
                    choice = (data.get('choices') or [{}])[0]
                    text = (choice.get('message') or {}).get('content') or ''
                    cut = choice.get('finish_reason') == 'length'
                if cancel.is_set():
                    raise Cancelled()
                if not text:
                    raise ModelError('模型没有返回回答正文')
                on_delta(text)
                if cut:
                    raise ModelError('回答达到输出长度上限，已保留部分内容，可继续追问')
                return
            done = False
            cut = False
            got_text = False
            for raw in response.iter_lines(chunk_size=64):
                if cancel.is_set():
                    raise Cancelled()
                line = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
                if not line.startswith('data:'):
                    continue
                value = line[5:].strip()
                if value == '[DONE]':
                    done = True
                    break
                try:
                    data = json.loads(value)
                except ValueError:
                    continue
                if data.get('error') or data.get('type') == 'error':
                    raise ModelError('模型服务在生成过程中返回错误，已保留接收到的内容')
                if anthropic:
                    delta = data.get('delta') or {}
                    text = delta.get('text') if data.get('type') == 'content_block_delta' else ''
                    if data.get('type') == 'message_stop':
                        done = True
                    if delta.get('stop_reason') == 'max_tokens':
                        cut = True
                else:
                    choice = (data.get('choices') or [{}])[0]
                    text = (choice.get('delta') or {}).get('content') or ''
                    if choice.get('finish_reason'):
                        done = True
                    if choice.get('finish_reason') == 'length':
                        cut = True
                if text and isinstance(text, str):
                    got_text = True
                    on_delta(text)
            if cancel.is_set():
                raise Cancelled()
            if cut:
                raise ModelError('回答达到输出长度上限，已保留部分内容，可继续追问')
            if not done:
                raise ModelError('网络流提前结束，部分回答已保存，可重试')
            if not got_text:
                raise ModelError('模型未返回回答正文；请检查模型配置或改用非推理模型')
    except (Cancelled, ModelError):
        raise
    except requests.RequestException:
        if cancel.is_set():
            raise Cancelled()
        raise ModelError('网络连接失败或等待超时，请检查 API 地址和网络后重试') from None
