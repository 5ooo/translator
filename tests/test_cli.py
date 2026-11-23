import io

import pytest

from PIL import Image

from ts import cli, engine, inputs
from ts.errors import TsError


def test_cli_result_only_on_stdout(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, 'stdin', io.StringIO('Hello'))
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')
    monkeypatch.setattr(cli.ArgosEngine, 'translate', lambda *args: '你好')
    assert cli.main([]) == 0
    output = capsys.readouterr()
    assert output.out == '你好\n'
    assert output.err == ''


def test_cli_empty_stdin(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, 'stdin', io.StringIO(''))
    assert cli.main([]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert '输入为空' in output.err


def test_conflicting_arguments():
    with pytest.raises(SystemExit) as error:
        cli.main(['--text', 'one', 'two'])
    assert error.value.code == 2


def test_check_failure_is_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'check', lambda: (False, ['缺少模型']))
    assert cli.main(['--check']) == 1
    assert '缺少模型' in capsys.readouterr().out


def test_missing_model_never_downloads(monkeypatch):
    monkeypatch.setattr(engine, 'local_packages', lambda: [])
    import sys
    import types
    monkeypatch.setitem(sys.modules, 'ctranslate2', types.SimpleNamespace())
    with pytest.raises(TsError, match='缺少本地 en→zh'):
        engine.ArgosEngine().translate('Hello', 'en', 'zh')


def test_local_model_import_is_not_supported():
    with pytest.raises(SystemExit) as error:
        cli.main(['--install-model', 'model.argosmodel'])
    assert error.value.code == 2


class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def image_cli(tmp_path, monkeypatch):
    path = tmp_path / '截图 sample.png'
    Image.new('RGB', (20, 20), 'white').save(path)
    state = {'ocr_text': '  Hello\n你好  \n', 'ocr_calls': 0, 'clipboard_type': 'image/png'}

    def run(args, **kwargs):
        if args[0] == 'tesseract':
            if '--list-langs' in args:
                return b'eng\nchi_sim\n'
            state['ocr_calls'] += 1
            assert kwargs['data'].startswith(b'\x89PNG')
            return state['ocr_text'].encode('utf-8')
        if '--list-types' in args or args[-1] == 'TARGETS':
            return (state['clipboard_type'] + '\n').encode()
        return path.read_bytes() if state['clipboard_type'] == 'image/png' else str(path).encode()

    monkeypatch.setattr(inputs, 'run', run)
    monkeypatch.setattr(inputs.shutil, 'which', lambda tool: tool)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.setattr(cli.sys, 'stdin', Tty())
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'zh' if text == '你好' else 'en')
    monkeypatch.setattr(cli.ArgosEngine, 'translate', lambda self, text, source, target: {'Hello': '你好', '你好': 'Hello'}[text])
    return path, state


@pytest.mark.parametrize(('route', 'ending'), [
    ('image', ''), ('positional', '\n'), ('stdin', '\n\n'),
    ('wayland-image', '\n'), ('x11-image', ''),
    ('wayland-path', '\n\n'), ('x11-path', '\n'),
])
def test_image_routes_show_original_and_translation(route, ending, image_cli, monkeypatch, capsys):
    path, state = image_cli
    state['ocr_text'] = '  Hello\n你好  ' + ending
    if route == 'image':
        args = ['--image', str(path)]
    elif route == 'positional':
        args = [str(path)]
    elif route == 'stdin':
        args = []
        monkeypatch.setattr(cli.sys, 'stdin', io.StringIO(str(path) + '\n'))
    else:
        args = []
        monkeypatch.setenv('WAYLAND_DISPLAY' if route.startswith('wayland') else 'DISPLAY', ':test')
        if route.endswith('path'):
            state['clipboard_type'] = 'text/plain;charset=utf-8'
    assert cli.main(args) == 0
    output = capsys.readouterr()
    original = '  Hello\n你好  ' + ending
    translation = '  你好\nHello  ' + ending
    assert output.out == ('原文：\n' + original + ('' if ending else '\n') + '\n译文：\n'
                          + translation + ('' if ending else '\n'))
    assert output.err == ''
    assert state['ocr_calls'] == 1


@pytest.mark.parametrize(('route', 'ending'), [
    ('positional', ''), ('text', '\n'), ('stdin', ''), ('wayland', '\n'), ('x11', ''),
])
def test_text_routes_keep_translation_only(route, ending, image_cli, monkeypatch, capsys):
    _, state = image_cli
    text = '  Hello\n你好  ' + ending
    if route in ('positional', 'text'):
        args = [text] if route == 'positional' else ['--text', text]
    elif route == 'stdin':
        args = []
        monkeypatch.setattr(cli.sys, 'stdin', io.StringIO(text))
    else:
        args = []
        monkeypatch.setenv('WAYLAND_DISPLAY' if route == 'wayland' else 'DISPLAY', ':test')
        replies = iter([b'text/plain;charset=utf-8\n', text.encode()])
        monkeypatch.setattr(inputs, 'run', lambda *a, **k: next(replies))
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert output.out == '  你好\nHello  \n'
    assert output.err == ''
    assert state['ocr_calls'] == 0


def test_forced_text_existing_image_path_has_no_headings(image_cli, capsys):
    path, state = image_cli
    assert cli.main(['--text', str(path)]) == 0
    output = capsys.readouterr()
    assert output.out == str(path) + '\n'
    assert output.err == ''
    assert state['ocr_calls'] == 0


@pytest.mark.parametrize('failure', ['empty-ocr', 'translation'])
def test_image_failure_leaves_stdout_empty(failure, image_cli, monkeypatch, capsys):
    path, state = image_cli
    if failure == 'empty-ocr':
        state['ocr_text'] = ' \n'
        expected = '图片中没有识别出文字'
    else:
        def fail(*args):
            raise TsError('本地模型推理失败')
        monkeypatch.setattr(cli.ArgosEngine, 'translate', fail)
        expected = '本地模型推理失败'
    assert cli.main(['--image', str(path)]) == 1
    output = capsys.readouterr()
    assert output.out == ''
    assert expected in output.err
    assert state['ocr_calls'] == 1


def test_resident_image_uses_host_ocr_once_and_shows_original(image_cli, monkeypatch, capsys):
    path, state = image_cli
    state['ocr_text'] = 'Hello\n你好\n'
    calls = []
    monkeypatch.setattr(cli, 'read_service_config', lambda: {'instance':'test'})
    def request(_config, operation, **kwargs):
        calls.append((operation, kwargs))
        return {'text':'你好\nHello\n'}
    monkeypatch.setattr(cli, 'request', request)
    assert cli.main(['--image', str(path)]) == 0
    assert capsys.readouterr().out == '原文：\nHello\n你好\n\n译文：\n你好\nHello\n'
    assert state['ocr_calls'] == 1
    assert calls[0][1]['text'] == 'Hello\n你好\n'
