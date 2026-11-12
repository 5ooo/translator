import io
import re

import pytest
from rich.cells import cell_len

from ts import cli
from ts.errors import TsError
from ts.events import Stage
from ts.inputs import InputResult
from ts.presentation import Presenter


class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def terminal(monkeypatch):
    monkeypatch.setenv('TERM', 'xterm-256color')
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.setenv('COLUMNS', '40')
    monkeypatch.setenv('LINES', '30')


@pytest.mark.parametrize('mode', ['pipe', 'no-color', 'dumb', 'unknown', 'plain'])
@pytest.mark.parametrize('origin', ['image', 'text'])
def test_plain_modes_preserve_bytes(mode, origin, monkeypatch):
    stdout = io.StringIO() if mode == 'pipe' else Tty()
    stderr = Tty()
    if mode == 'no-color':
        monkeypatch.setenv('NO_COLOR', '')
    if mode in ('dumb', 'unknown'):
        monkeypatch.setenv('TERM', mode)
    with Presenter(stdout, stderr, plain=mode == 'plain') as ui:
        ui.stage(Stage.OCR)
        ui.result(InputResult('  source\n\n', origin), '  target\n\n')
    expected = '原文：\n  source\n\n\n译文：\n' if origin == 'image' else ''
    assert stdout.getvalue() == expected + '  target\n\n'
    assert stderr.getvalue() == ''


@pytest.mark.parametrize('origin', ['image', 'text'])
@pytest.mark.parametrize('ending', ['', '\n', '\n\n'])
def test_terminal_shows_original_and_translation_on_two_lines(origin, ending):
    stdout = Tty()
    with Presenter(stdout, io.StringIO()) as ui:
        ui.result(InputResult('Hello world.' + ending, origin), '你好，世界。' + ending)
    rendered = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', stdout.getvalue())
    assert rendered == '原文：Hello world.\n译文：你好，世界。\n'


@pytest.mark.parametrize(('origin', 'source', 'expected'), [
    ('text', 'first\nsecond', '原文：first\nsecond\n\n译文：done\n'),
    ('text', '中' * 17, '原文：' + '中' * 17 + '\n译文：done\n'),
    ('image', '中' * 18, '原文：' + '中' * 17 + '\n中\n\n译文：done\n'),
])
def test_terminal_separates_wrapped_original(origin, source, expected):
    stdout = Tty()
    with Presenter(stdout, io.StringIO()) as ui:
        ui.result(InputResult(source, origin), 'done')
    rendered = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', stdout.getvalue())
    assert rendered == expected


def test_narrow_terminal_wraps_literal_content():
    stdout, stderr = Tty(), io.StringIO()
    literal = '[red] 网络已就绪。\n/home/user/截图 [red]/network.png\nhttps://example.com/' + 'x' * 95
    with Presenter(stdout, stderr) as ui:
        ui.stage(Stage.MODEL)
        ui.result(InputResult('The network is ready.\n请检查API和GPU状态。', 'image'), literal)
    rendered = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', stdout.getvalue())
    assert '[red]' in rendered
    assert '网络已就绪。' in rendered
    assert '请检查API和GPU状态。' in rendered
    assert 'https://example.com/' + 'x' * 95 in rendered.replace('\n', '')
    assert all(cell_len(line) <= 40 for line in rendered.splitlines())
    assert '原文：The network is ready.' in rendered
    assert '译文：[red] 网络已就绪。' in rendered
    assert stderr.getvalue() == ''


@pytest.mark.parametrize('failure, code', [(TsError('推理失败'), 1), (KeyboardInterrupt(), 130)])
def test_cli_failure_restores_cursor_before_error(failure, code, monkeypatch):
    stdout, stderr = Tty(), Tty()
    monkeypatch.setattr(cli.sys, 'stdout', stdout)
    monkeypatch.setattr(cli.sys, 'stderr', stderr)
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')

    def fail(*args):
        raise failure

    monkeypatch.setattr(cli.ArgosEngine, 'translate', fail)
    assert cli.main(['--text', 'Hello']) == code
    assert stdout.getvalue() == ''
    captured = stderr.getvalue()
    assert '\x1b[?25l' in captured
    assert '\x1b[?25h' in captured
    if code == 1:
        assert captured.index('\x1b[?25h') < captured.index('ts：推理失败')
    else:
        assert 'ts：' not in captured


def test_plain_flag_combines_with_text(monkeypatch):
    stdout, stderr = Tty(), Tty()
    monkeypatch.setattr(cli.sys, 'stdout', stdout)
    monkeypatch.setattr(cli.sys, 'stderr', stderr)
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')
    monkeypatch.setattr(cli.ArgosEngine, 'translate', lambda *args: '你好')
    assert cli.main(['--plain', '--text', 'Hello']) == 0
    assert stdout.getvalue() == '你好\n'
    assert stderr.getvalue() == ''
