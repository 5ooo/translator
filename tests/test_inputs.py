import io
import subprocess

import pytest
from PIL import Image

from ts import inputs
from ts.events import Stage
from ts.errors import TsError


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_explicit_text_wins_over_pipe_and_clipboard(monkeypatch):
    monkeypatch.setattr(inputs, 'clipboard_text', lambda: pytest.fail('clipboard read'))
    assert inputs.read_input(['hello'], None, None, io.StringIO('pipe')) == inputs.InputResult('hello', 'text')
    assert inputs.read_input([], 'hello.png', None, io.StringIO('pipe')) == inputs.InputResult('hello.png', 'text')


def test_pipe_wins_over_clipboard(monkeypatch):
    monkeypatch.setattr(inputs, 'clipboard_text', lambda: pytest.fail('clipboard read'))
    assert inputs.read_input([], None, None, io.StringIO('pipe')) == inputs.InputResult('pipe', 'text')


def test_tty_uses_clipboard(monkeypatch):
    monkeypatch.setattr(inputs, 'clipboard_text', lambda **kwargs: inputs.InputResult('clipboard', 'text'))
    assert inputs.read_input([], None, None, Tty()) == inputs.InputResult('clipboard', 'text')


def test_empty_pipe_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(inputs, 'clipboard_text', lambda: pytest.fail('clipboard read'))
    with pytest.raises(TsError, match='输入为空'):
        inputs.read_input([], None, None, io.StringIO(''))


def test_single_image_path_in_args_and_stdin(tmp_path, monkeypatch):
    path = tmp_path / 'a b.png'
    path.write_bytes(b'fake')
    monkeypatch.setattr(inputs, 'ocr', lambda data, **kwargs: 'Hello image')
    assert inputs.read_input([str(path)], None, None, Tty()) == inputs.InputResult('Hello image', 'image')
    assert inputs.read_input([], None, None, io.StringIO(str(path) + '\n')) == inputs.InputResult('Hello image', 'image')
    assert inputs.read_input([], str(path), None, Tty()) == inputs.InputResult(str(path), 'text')


def test_missing_explicit_image():
    with pytest.raises(TsError, match='无法读取图片'):
        inputs.image_text('/does/not/exist.png')


@pytest.mark.parametrize('wayland', [True, False])
def test_clipboard_prefers_image_and_passes_bytes(wayland, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return b'text/plain\nimage/png\n' if len(calls) == 1 else b'PNG'
    monkeypatch.setattr(inputs, 'run', run)
    monkeypatch.setattr(inputs, 'ocr', lambda data, **kwargs: 'OCR ' + data.decode())
    assert inputs.clipboard_backend(wayland) == inputs.InputResult('OCR PNG', 'image')
    assert calls[-1][-1] == 'image/png'
    assert calls[-1][0] == ('wl-paste' if wayland else 'xclip')


@pytest.mark.parametrize('wayland', [True, False])
def test_clipboard_text(wayland, monkeypatch):
    replies = iter([b'text/plain;charset=utf-8\n', '你好'.encode()])
    monkeypatch.setattr(inputs, 'run', lambda *a, **k: next(replies))
    assert inputs.clipboard_backend(wayland) == inputs.InputResult('你好', 'text')


def test_wayland_failure_falls_back_to_x11(monkeypatch):
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setattr(inputs.shutil, 'which', lambda tool: tool)
    def backend(wayland, **kwargs):
        if wayland:
            raise TsError('Wayland unavailable')
        return inputs.InputResult('X11', 'text')
    monkeypatch.setattr(inputs, 'clipboard_backend', backend)
    assert inputs.clipboard_text() == inputs.InputResult('X11', 'text')


def test_no_session(monkeypatch):
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.delenv('DISPLAY', raising=False)
    with pytest.raises(TsError, match='显示会话'):
        inputs.clipboard_text()


def png():
    data = io.BytesIO()
    Image.new('RGB', (20, 20), 'white').save(data, format='PNG')
    return data.getvalue()


@pytest.mark.parametrize('variant', ['tiny', 'small'])
def test_ocr_uses_selected_variant(monkeypatch, variant):
    calls = []
    def recognize(data, selected):
        calls.append((data, selected))
        return 'Hello\n'
    monkeypatch.setattr(inputs, 'recognize', recognize)
    assert inputs.ocr(png(), variant=variant) == 'Hello\n'
    assert calls == [(png(), variant)]


def test_ocr_missing_model_reports_error(monkeypatch):
    def missing(*args):
        raise TsError('缺少 OCR 模型')
    monkeypatch.setattr(inputs, 'recognize', missing)
    with pytest.raises(TsError, match='缺少 OCR 模型'):
        inputs.ocr(png())


def test_invalid_image():
    with pytest.raises(TsError, match='无法解码图片'):
        inputs.ocr(b'not image')


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.TimeoutExpired('tool', 5)])
def test_tool_errors_are_readable(error, monkeypatch):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(inputs.subprocess, 'run', fail)
    with pytest.raises(TsError):
        inputs.run(['tool'])


def test_ocr_announces_before_external_work(monkeypatch):
    stages = []

    def recognize(data, variant):
        assert stages == [Stage.OCR]
        return 'Hello'

    monkeypatch.setattr(inputs, 'recognize', recognize)
    assert inputs.ocr(png(), on_stage=stages.append) == 'Hello'
