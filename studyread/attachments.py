"""Validated local image attachments, shared by chat, export and cleanup."""
import base64
import binascii
import struct
import uuid

import pymupdf

from .config import data_dir

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def image_names(context):
    names = ([context['image']] if context.get('image') else []) + context.get('images', [])
    return list(dict.fromkeys(names))


def decode_images(values):
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > MAX_IMAGES:
        raise ValueError('每条问题最多粘贴 4 张图片')
    images, total = [], 0
    for value in values:
        if not isinstance(value, str) or not value.startswith('data:image/png;base64,'):
            raise ValueError('图片格式无效，请重新粘贴截图')
        try:
            raw = base64.b64decode(value.split(',', 1)[1], validate=True)
            total += len(raw)
            if total > MAX_IMAGE_BYTES:
                raise ValueError('粘贴图片总大小不能超过 8MB，请缩小图片后重试')
            if len(raw) < 33 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
                raise ValueError('图片格式无效，请重新粘贴截图')
            width, height = struct.unpack('>II', raw[16:24])
            if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16_000_000):
                raise ValueError('图片尺寸过大，请缩小图片后重试')
            pix = pymupdf.Pixmap(raw)
            if pix.width != width or pix.height != height:
                raise ValueError('图片尺寸无效')
        except (binascii.Error, RuntimeError) as exc:
            raise ValueError('图片损坏，请重新粘贴截图') from exc
        images.append(raw)
    return images


def save_images(images):
    names = []
    for raw in images:
        name = uuid.uuid4().hex + '.png'
        (data_dir() / 'attachments' / name).write_bytes(raw)
        names.append(name)
    return names
