import io
import json
import re
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ts import cli, inputs, models
from ts.errors import TsError
from ts.inputs import InputResult


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_translation(monkeypatch):
    calls = []

    class Translator:
        def __init__(self, name):
            self.name = name

        def translate(self, text, source, target):
            calls.append(('translate', self.name, text, source, target))
            return f'{self.name}-result'

    @contextmanager
    def open_fake(name, *, on_stage=None):
        calls.append(('open', name))
        try:
            yield Translator(name)
        finally:
            calls.append(('close', name))

    monkeypatch.setattr(cli, 'open_translator', open_fake)
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')
    return calls


def test_models_does_not_read_clipboard_or_create_config(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'read_input', lambda *args, **kwargs: pytest.fail('管理命令读取了输入'))
    monkeypatch.setattr(cli, 'available', lambda name: (name != 'plamo', 'ready' if name != 'plamo' else '缺少模型文件'))
    assert cli.main(['--models']) == 0
    output = capsys.readouterr().out
    assert output == '* 速度优先\n  效果优先（不可用）\n'
    assert not models.config_path().exists()

    path = models.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"model":"plamo"}', encoding='utf-8')
    monkeypatch.setattr(cli, 'available', lambda name: (True, 'ready'))
    assert cli.main(['--models']) == 0
    assert capsys.readouterr().out == '  速度优先\n* 效果优先\n'


@pytest.mark.parametrize('selected', ['argos', 'plamo'])
@pytest.mark.parametrize('mode', ['terminal', 'pipe', 'no-color', 'dumb', 'unknown', 'plain'])
def test_models_marks_and_colors_current_mode(selected, mode, monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    stdout = io.StringIO() if mode == 'pipe' else Tty()
    monkeypatch.setattr(cli.sys, 'stdout', stdout)
    monkeypatch.setattr(cli.sys, 'stderr', io.StringIO())
    monkeypatch.setattr(cli, 'default_model', lambda: selected)
    monkeypatch.setattr(cli, 'available', lambda name: (True, 'ready'))
    monkeypatch.setenv('TERM', mode if mode in ('dumb', 'unknown') else 'xterm-256color')
    monkeypatch.delenv('NO_COLOR', raising=False)
    if mode == 'no-color':
        monkeypatch.setenv('NO_COLOR', '')
    args = ['--models', '--plain'] if mode == 'plain' else ['--models']
    assert cli.main(args) == 0
    output = stdout.getvalue()
    plain = re.sub(r'\x1b\[[0-9;]*m', '', output)
    if selected == 'argos':
        assert plain == '* 速度优先\n  效果优先\n'
        selected_line, other_line = output.splitlines()
    else:
        assert plain == '  速度优先\n* 效果优先\n'
        other_line, selected_line = output.splitlines()
    if mode == 'terminal':
        assert '\x1b[' in selected_line
        assert '\x1b[' not in other_line
    else:
        assert output == plain


def test_saved_model_and_one_shot_override(fake_translation, monkeypatch, capsys):
    path = models.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"model":"plamo"}', encoding='utf-8')
    assert cli.main(['--text', 'Hello']) == 0
    assert capsys.readouterr().out == 'plamo-result\n'
    assert cli.main(['--model', 'argos', '--text', 'Hello']) == 0
    assert capsys.readouterr().out == 'argos-result\n'
    assert models.default_model() == 'plamo'
    assert fake_translation == [
        ('open', 'plamo'), ('translate', 'plamo', 'Hello', 'en', 'zh'), ('close', 'plamo'),
        ('open', 'argos'), ('translate', 'argos', 'Hello', 'en', 'zh'), ('close', 'argos'),
    ]


def test_set_model_preserves_other_settings_and_failed_replace(monkeypatch):
    monkeypatch.setattr(models, 'available', lambda name: (True, 'ready'))
    path = models.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"model":"argos","other":"keep"}', encoding='utf-8')
    models.set_default('plamo')
    before = path.read_bytes()
    assert json.loads(before) == {'model': 'plamo', 'other': 'keep'}

    def fail_replace(*args):
        raise OSError('只读文件系统')

    monkeypatch.setattr(models.os, 'replace', fail_replace)
    with pytest.raises(TsError, match='无法保存模型配置'):
        models.set_default('argos')
    assert path.read_bytes() == before
    assert list(path.parent.glob('.config-*')) == []


def test_unavailable_model_cannot_be_saved(monkeypatch, capsys):
    monkeypatch.setattr(models, 'available', lambda name: (False, '缺少本地模型文件'))
    with pytest.raises(TsError, match='缺少本地模型文件'):
        models.set_default('plamo')
    output = capsys.readouterr()
    assert not output.out
    assert not models.config_path().exists()


def test_corrupt_config_reports_error_but_explicit_override_works(fake_translation, capsys):
    path = models.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('{broken', encoding='utf-8')
    assert cli.main(['--text', 'Hello']) == 1
    output = capsys.readouterr()
    assert not output.out
    assert '模型配置' in output.err
    assert cli.main(['--model', 'argos', '--text', 'Hello']) == 0
    assert capsys.readouterr().out == 'argos-result\n'
    assert path.read_text(encoding='utf-8') == '{broken'


@pytest.mark.parametrize('config', ['[]', '{"model":"missing"}', '{"model":null}'])
def test_invalid_config_never_falls_back(config, capsys):
    path = models.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(config, encoding='utf-8')
    assert cli.main(['--text', 'Hello']) == 1
    output = capsys.readouterr()
    assert not output.out
    assert '模型' in output.err


def test_selected_missing_model_reports_error_without_fallback(monkeypatch, capsys):
    class Missing:
        def __init__(self, *, on_stage=None):
            pass

        def translate(self, *args):
            raise TsError('缺少 PLaMo 本地模型')

        def close(self):
            pass

    monkeypatch.setattr(models, '_module', lambda name: SimpleNamespace(PlamoEngine=Missing))
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')
    assert cli.main(['--model', 'plamo', '--text', 'Hello']) == 1
    output = capsys.readouterr()
    assert output.out == ''
    assert '缺少 PLaMo 本地模型' in output.err


@pytest.mark.parametrize(('failure', 'code'), [(TsError('模型出错'), 1), (KeyboardInterrupt(), 130)])
def test_selected_model_closes_on_failure(failure, code, monkeypatch, capsys):
    closed = []

    class Failing:
        def __init__(self, *, on_stage=None):
            pass

        def translate(self, *args):
            raise failure

        def close(self):
            closed.append(True)

    monkeypatch.setattr(models, '_module', lambda name: SimpleNamespace(PlamoEngine=Failing))
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')
    assert cli.main(['--model', 'plamo', '--text', 'Hello']) == code
    assert closed == [True]
    output = capsys.readouterr()
    assert output.out == ''
    if code == 1:
        assert '模型出错' in output.err


def test_check_uses_selected_model(monkeypatch, capsys):
    selected = []
    monkeypatch.setattr(cli, 'check', lambda name='argos': (selected.append(name) or True, ['检查完成']))
    monkeypatch.setattr(cli, 'read_input', lambda *args, **kwargs: pytest.fail('自检读取了输入'))
    assert cli.main(['--check', '--model', 'plamo']) == 0
    assert selected == ['plamo']
    assert capsys.readouterr().out == '检查完成\n'


def test_model_choice_preserves_explicit_input_priority(fake_translation, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, 'stdin', io.StringIO('ignored'))
    assert cli.main(['--model', 'plamo', '--text', 'Hello']) == 0
    assert capsys.readouterr().out == 'plamo-result\n'
    assert ('translate', 'plamo', 'Hello', 'en', 'zh') in fake_translation


def test_model_choice_reads_clipboard_without_positional_input(fake_translation, monkeypatch, capsys):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(cli.sys, 'stdin', Tty())
    monkeypatch.setattr(inputs, 'clipboard_text', lambda **kwargs: InputResult('Hello', 'text'))
    assert cli.main(['--model', 'plamo']) == 0
    assert capsys.readouterr().out == 'plamo-result\n'
    assert ('translate', 'plamo', 'Hello', 'en', 'zh') in fake_translation


def test_model_choice_preserves_image_original(fake_translation, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'read_input', lambda *args, **kwargs: InputResult('Hello\n', 'image'))
    assert cli.main(['--model', 'plamo', '--image', 'local.png']) == 0
    assert capsys.readouterr().out == '原文：\nHello\n\n译文：\nplamo-result\n'


@pytest.mark.parametrize('args', [
    ['--model', 'unknown'], ['--set-model', 'unknown'],
    ['--model', 'qwen'], ['--model', 'm2m'], ['--set-model', 'qwen'], ['--set-model', 'm2m'],
    ['--models', '--set-model', 'argos'], ['--model', 'plamo', '--set-model', 'argos'],
    ['--models', 'Hello'],
])
def test_invalid_options_are_rejected_without_writing_config(args):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    assert not models.config_path().exists()


@pytest.mark.parametrize('old_model', ['qwen', 'm2m'])
def test_removed_default_requires_interactive_reselection(old_model, capsys):
    path = models.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'model': old_model, 'other': 'keep'}), encoding='utf-8')
    assert cli.main(['--models']) == 1
    assert 'ts --models' in capsys.readouterr().err
    assert json.loads(path.read_text(encoding='utf-8')) == {'model': old_model, 'other': 'keep'}


def test_removed_set_model_is_not_advertised_or_accepted(capsys):
    with pytest.raises(SystemExit) as help_exit:
        cli.main(['--help'])
    assert help_exit.value.code == 0
    assert '--set-model' not in capsys.readouterr().out
    with pytest.raises(SystemExit) as option_exit:
        cli.main(['--set-model', 'plamo'])
    assert option_exit.value.code == 2
    assert not models.config_path().exists()
