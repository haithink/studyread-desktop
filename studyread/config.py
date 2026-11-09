import json
import os
from pathlib import Path
import tempfile
import threading
import uuid

_LOCK = threading.RLock()


def data_dir():
    override = os.environ.get('STUDYREAD_DATA_DIR')
    root = Path(override) if override else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'StudyRead'
    root.mkdir(parents=True, exist_ok=True)
    return root


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
            name = file.name
            json.dump(value, file, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def settings():
    with _LOCK:
        try:
            result = json.loads((data_dir() / 'settings.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            result = {}
    return {'profiles': [], 'activeProfile': '', **result}


def public_settings():
    result = settings()
    result['profiles'] = [{k: v for k, v in p.items() if k != 'apiKey'} |
                          {'hasKey': bool(p.get('apiKey'))} for p in result['profiles']]
    return result


def save_settings(value):
    with _LOCK:
        current = settings()
        profiles = []
        for p in value.get('profiles', []):
            old = next((x for x in current['profiles'] if x['id'] == p.get('id')), {})
            new = {k: str(p.get(k, '')).strip() for k in ('name', 'provider', 'baseUrl', 'model')}
            if new['provider'] not in ('openai', 'anthropic'):
                raise ValueError('请选择 OpenAI 兼容或 Anthropic 接口')
            if not new['baseUrl'].startswith(('https://', 'http://')):
                raise ValueError('API 地址必须以 http:// 或 https:// 开头')
            if not new['name'] or not new['model']:
                raise ValueError('请填写配置名称和模型名')
            new.update(id=p.get('id') or uuid.uuid4().hex, vision=p.get('vision') is True,
                       apiKey=str(p.get('apiKey') or old.get('apiKey', '')).strip())
            profiles.append(new)
        active = value.get('activeProfile')
        if active not in [p['id'] for p in profiles]:
            active = profiles[0]['id'] if profiles else ''
        atomic_json(data_dir() / 'settings.json', {'profiles': profiles, 'activeProfile': active})
    return public_settings()


def profile():
    current = settings()
    p = next((p for p in current['profiles'] if p['id'] == current['activeProfile']), None)
    if not p or not p.get('apiKey'):
        raise ValueError('请先在模型设置中配置 API 地址、密钥和模型')
    return p


def import_kandu():
    source = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'KanduDesktop' / 'settings.json'
    if not source.is_file():
        raise ValueError('未找到本机刊读的模型配置')
    data = json.loads(source.read_text(encoding='utf-8'))
    profiles = []
    for p in data.get('llms', []):
        if p.get('baseUrl') and p.get('model'):
            profiles.append({**{k: p.get(k, '') for k in ('name', 'baseUrl', 'apiKey', 'model')},
                             'id': uuid.uuid4().hex, 'provider': p.get('provider', 'openai'), 'vision': False})
    if not profiles:
        raise ValueError('刊读中没有可导入的配置')
    current = settings()
    existing = {(p['baseUrl'], p['model']) for p in current['profiles']}
    additions = [p for p in profiles if (p['baseUrl'], p['model']) not in existing]
    return save_settings({'profiles': current['profiles'] + additions,
                          'activeProfile': current['activeProfile'] or profiles[0]['id']})
