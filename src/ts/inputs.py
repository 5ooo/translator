import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Literal, TextIO

from .errors import TsError
from .events import Stage, StageObserver, emit
from .ocr import recognize

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp', '.gif'}
IMAGE_MIMES = ('image/png', 'image/jpeg', 'image/tiff', 'image/bmp', 'image/webp', 'image/gif')


@dataclass(frozen=True)
class InputResult:
    text: str
    origin: Literal['text', 'image']


def run(args, *, data=None, timeout=5):
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise TsError(f'缺少系统工具：{args[0]}') from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TsError(f'{args[0]} 执行失败或超时：{exc}') from exc
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace').strip()
        raise TsError(f'{args[0]} 执行失败：{detail or result.returncode}')
    return result.stdout


def decode_text(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise TsError('文字输入必须为 UTF-8；图片请使用文件路径或剪贴板图片。') from exc


def ocr(data: bytes, *, variant: str = 'tiny', backend=None, on_stage: StageObserver | None = None) -> str:
    emit(on_stage, Stage.OCR)
    return (backend if backend is not None else recognize)(data, variant)


def image_text(path: str | Path, *, ocr_variant: str = 'tiny', ocr_backend=None,
               on_stage: StageObserver | None = None) -> InputResult:
    emit(on_stage, Stage.READ)
    source = Path(path).expanduser()
    try:
        return InputResult(ocr(source.read_bytes(), variant=ocr_variant, backend=ocr_backend, on_stage=on_stage), 'image')
    except OSError as exc:
        raise TsError(f'无法读取图片 {source}：{exc.strerror}') from exc


def as_text(value: str, *, ocr_variant: str = 'tiny', ocr_backend=None,
            on_stage: StageObserver | None = None) -> InputResult:
    candidate = value.strip()
    if '\n' not in candidate and '\r' not in candidate:
        path = Path(candidate).expanduser()
        try:
            if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
                return image_text(path, ocr_variant=ocr_variant, ocr_backend=ocr_backend, on_stage=on_stage)
        except OSError:
            pass
    return InputResult(value, 'text')


def clipboard_backend(wayland: bool, *, ocr_variant: str = 'tiny', ocr_backend=None,
                      on_stage: StageObserver | None = None) -> InputResult:
    emit(on_stage, Stage.CLIPBOARD)
    listing = ['wl-paste', '--list-types'] if wayland else ['xclip', '-selection', 'clipboard', '-o', '-t', 'TARGETS']
    types = decode_text(run(listing)).splitlines()
    mime = next((kind for kind in IMAGE_MIMES if kind in types), None)
    if mime is None:
        mime = next((kind for kind in ('text/plain;charset=utf-8', 'UTF8_STRING', 'text/plain', 'STRING') if kind in types), None)
    if mime is None:
        raise TsError('剪贴板没有支持的图片或文字。')
    args = ['wl-paste', '--no-newline', '--type', mime] if wayland else ['xclip', '-selection', 'clipboard', '-o', '-t', mime]
    data = run(args)
    return (InputResult(ocr(data, variant=ocr_variant, backend=ocr_backend, on_stage=on_stage), 'image')
            if mime.startswith('image/') else as_text(decode_text(data), ocr_variant=ocr_variant,
                                                       ocr_backend=ocr_backend, on_stage=on_stage))


def clipboard_text(*, ocr_variant: str = 'tiny', ocr_backend=None,
                   on_stage: StageObserver | None = None) -> InputResult:
    errors = []
    for display, tool, wayland in [('WAYLAND_DISPLAY', 'wl-paste', True), ('DISPLAY', 'xclip', False)]:
        if os.environ.get(display):
            if not shutil.which(tool):
                errors.append(f'缺少 {tool}')
                continue
            try:
                text = clipboard_backend(wayland, ocr_variant=ocr_variant, ocr_backend=ocr_backend, on_stage=on_stage)
                if not text.text.strip():
                    raise TsError('剪贴板为空。')
                return text
            except TsError as exc:
                errors.append(str(exc))
    raise TsError('无法读取剪贴板：' + ('；'.join(errors) if errors else '没有 X11 或 Wayland 显示会话。'))


def read_input(values: list[str], text: str | None, image: str | None, stdin: TextIO,
               *, ocr_variant: str = 'tiny', ocr_backend=None, on_stage: StageObserver | None = None) -> InputResult:
    emit(on_stage, Stage.READ)
    if text is not None:
        result = InputResult(text, 'text')
    elif image is not None:
        result = image_text(image, ocr_variant=ocr_variant, ocr_backend=ocr_backend, on_stage=on_stage)
    elif values:
        result = (as_text(values[0], ocr_variant=ocr_variant, ocr_backend=ocr_backend, on_stage=on_stage)
                  if len(values) == 1 else InputResult(' '.join(values), 'text'))
    elif not stdin.isatty():
        try:
            result = as_text(stdin.read(), ocr_variant=ocr_variant, ocr_backend=ocr_backend, on_stage=on_stage)
        except (UnicodeError, OSError) as exc:
            raise TsError(f'无法读取 UTF-8 stdin：{exc}') from exc
    else:
        result = clipboard_text(ocr_variant=ocr_variant, ocr_backend=ocr_backend, on_stage=on_stage)
    if not result.text.strip():
        raise TsError('输入为空。')
    return result
