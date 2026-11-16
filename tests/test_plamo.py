import json
import os
from pathlib import Path
import socket

import pytest

from ts import cli, models, plamo
from ts.errors import TsError
from ts.events import Stage


@pytest.fixture
def fake_runner(tmp_path, monkeypatch):
    executable = tmp_path / 'llama-server'
    executable.write_text('''#!/usr/bin/python3
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

log = os.environ['TS_PLAMO_TEST_LOG']
def record(value):
    with open(log, 'a', encoding='utf-8') as file:
        file.write(json.dumps(value, ensure_ascii=False) + '\\n')

layers = sys.argv[sys.argv.index('--n-gpu-layers') + 1]
record({'event': 'start', 'pid': os.getpid(), 'model': sys.argv[sys.argv.index('-m') + 1],
        'gpu_layers': layers, 'cuda_visible': os.environ.get('CUDA_VISIBLE_DEVICES')})
if os.environ.get('TS_PLAMO_TEST_GPU_FAIL') and layers != '0':
    sys.exit(1)

class Handler(BaseHTTPRequestHandler):
    health = 0
    def log_message(self, *args):
        pass
    def respond(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer ' + os.environ['LLAMA_API_KEY']:
            self.respond({'error':'unauthorized'}, 401)
            return
        Handler.health += 1
        if Handler.health == 1:
            self.respond({'status':'loading model'}, 503)
        else:
            self.respond({'status':'ok'})
    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer ' + os.environ['LLAMA_API_KEY']:
            self.respond({'error':'unauthorized'}, 401)
            return
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        record({'event':'request', 'request':request})
        if 'FORCE_LENGTH' in request['prompt']:
            self.respond({'content':'partial', 'stop_type':'limit', 'truncated':False})
        else:
            self.respond({'content':'translation', 'stop_type':'eos', 'truncated':False})

HTTPServer(('127.0.0.1', 0), Handler).serve_forever()
''')
    executable.chmod(0o755)
    model = tmp_path / 'model.gguf'
    model.write_bytes(b'model')
    log = tmp_path / 'events.jsonl'
    monkeypatch.setenv('TS_PLAMO_MODEL', str(model))
    monkeypatch.setenv('TS_PLAMO_RUNNER', str(executable))
    monkeypatch.setenv('TS_PLAMO_TEST_LOG', str(log))
    monkeypatch.setenv('TS_PLAMO_DEVICE', 'cpu')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    return model, log


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def assert_reaped(pid):
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_model_is_listed_and_can_be_selected(fake_runner, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')
    assert cli.main(['--models']) == 0
    assert '  效果优先\n' in capsys.readouterr().out
    assert cli.main(['--model', 'plamo', '--plain', '--text', 'Hello world.']) == 0
    assert capsys.readouterr().out == 'translation\n'
    assert models.default_model() == 'argos'
    assert cli.main(['--set-model', 'plamo']) == 0
    assert models.default_model() == 'plamo'
    assert cli.main(['--plain', '--text', 'Hello world.']) == 0
    assert capsys.readouterr().out.endswith('translation\n')


def test_default_requires_q4_instead_of_old_q3(fake_runner, monkeypatch, tmp_path, capsys):
    _, log = fake_runner
    monkeypatch.delenv('TS_PLAMO_MODEL')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setattr(plamo, '_ROOT', tmp_path / 'empty-project')
    monkeypatch.setattr(cli, 'Detector', lambda: lambda text: 'en')
    directory = tmp_path / 'data/ts/models/plamo3'
    directory.mkdir(parents=True)
    (directory / 'plamo-3-translate-0.8b-Q3_K_M.gguf').write_bytes(b'old model')

    assert cli.main(['--models']) == 0
    assert '  效果优先（不可用）\n' in capsys.readouterr().out

    model = directory / 'plamo-3-translate-0.8b-Q4_K_M.gguf'
    model.write_bytes(b'new model')
    assert cli.main(['--model', 'plamo', '--plain', '--text', 'Hello world.']) == 0
    assert capsys.readouterr().out == 'translation\n'
    assert events(log)[0]['model'] == str(model)


def test_reuses_private_runner_and_translates_both_directions(fake_runner, monkeypatch):
    model, log = fake_runner
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY', '')
    stages = []
    engine = plamo.PlamoEngine(on_stage=stages.append)
    try:
        assert engine.translate('Hello world.', 'en', 'zh') == 'translation'
        assert engine.translate('你好，世界。', 'zh', 'en') == 'translation'
    finally:
        engine.close()
        engine.close()
    recorded = events(log)
    starts = [item for item in recorded if item['event'] == 'start']
    requests = [item['request'] for item in recorded if item['event'] == 'request']
    assert len(starts) == 1 and starts[0]['model'] == str(model)
    assert starts[0]['gpu_layers'] == '0' and starts[0]['cuda_visible'] == '-1'
    assert_reaped(starts[0]['pid'])
    assert len(requests) == 2
    assert 'Hello world.' in requests[0]['prompt'] and '<|plamo:val|>zh-hans' in requests[0]['prompt']
    assert '你好，世界。' in requests[1]['prompt'] and '<|plamo:val|>en' in requests[1]['prompt']
    assert stages == [Stage.MODEL, Stage.TRANSLATE, Stage.TRANSLATE]


def test_incomplete_result_cleans_up_private_runner(fake_runner):
    _, log = fake_runner
    engine = plamo.PlamoEngine()
    with pytest.raises(TsError, match='不完整'):
        engine.translate('FORCE_LENGTH', 'en', 'zh')
    assert_reaped(events(log)[0]['pid'])


def test_control_tokens_and_oversize_are_rejected_before_start(fake_runner):
    _, log = fake_runner
    engine = plamo.PlamoEngine()
    with pytest.raises(TsError, match='模型控制标记'):
        engine.translate('<|plamo:tag|>bad', 'en', 'zh')
    with pytest.raises(TsError, match='过长'):
        engine.translate('😀' * 600, 'en', 'zh')
    assert not log.exists()


def test_unavailable_explicit_resources_do_not_fall_back(fake_runner, monkeypatch, tmp_path):
    monkeypatch.setenv('TS_PLAMO_MODEL', str(tmp_path / 'missing.gguf'))
    ready, reason = plamo.available()
    assert not ready and 'TS_PLAMO_MODEL' in reason
    monkeypatch.setenv('TS_PLAMO_MODEL', str(fake_runner[0]))
    monkeypatch.setenv('TS_PLAMO_RUNNER', str(tmp_path / 'missing-runner'))
    ready, reason = plamo.available()
    assert not ready and 'TS_PLAMO_RUNNER' in reason


def test_failed_gpu_start_falls_back_to_cpu(fake_runner, monkeypatch):
    _, log = fake_runner
    monkeypatch.setenv('TS_PLAMO_DEVICE', 'auto')
    monkeypatch.setenv('TS_PLAMO_TEST_GPU_FAIL', '1')
    engine = plamo.PlamoEngine()
    try:
        assert engine.translate('Hello.', 'en', 'zh') == 'translation'
    finally:
        engine.close()
    starts = [item for item in events(log) if item['event'] == 'start']
    assert [item['gpu_layers'] for item in starts] == ['999', '0']
    for item in starts:
        assert_reaped(item['pid'])


def test_default_gpu_failure_uses_bundled_cpu(fake_runner, monkeypatch, tmp_path):
    _, log = fake_runner
    source = Path(os.environ['TS_PLAMO_RUNNER'])
    for name in ('llama-b12110-vulkan', 'llama-b12110-cpu'):
        directory = tmp_path / '.runtime/tools' / name
        directory.mkdir(parents=True)
        (directory / 'llama-server').write_bytes(source.read_bytes())
        (directory / 'llama-server').chmod(0o755)
    monkeypatch.setattr(plamo, '_ROOT', tmp_path)
    monkeypatch.delenv('TS_PLAMO_RUNNER')
    monkeypatch.setenv('TS_PLAMO_DEVICE', 'auto')
    monkeypatch.setenv('TS_PLAMO_TEST_GPU_FAIL', '1')
    engine = plamo.PlamoEngine()
    try:
        assert engine.translate('Hello.', 'en', 'zh') == 'translation'
    finally:
        engine.close()
    starts = [item for item in events(log) if item['event'] == 'start']
    assert [item['gpu_layers'] for item in starts] == ['999', '0']
    for item in starts:
        assert_reaped(item['pid'])


@pytest.mark.parametrize('response', [b'bad json', b'{}', b'{"content":"partial","stop_type":"limit"}',
                                       b'{"content":"partial","stop_type":"eos","truncated":true}',
                                       b'{"content":" ","stop_type":"eos"}'])
def test_invalid_or_incomplete_response_is_not_returned(response):
    with pytest.raises(TsError):
        plamo._parse_response(response)


def test_input_is_not_sent_to_another_process_listener(fake_runner, monkeypatch):
    _, log = fake_runner
    engine = plamo.PlamoEngine()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unrelated:
        unrelated.bind(('127.0.0.1', 0))
        unrelated.listen(1)
        unrelated.settimeout(2)
        engine._start()
        pid = events(log)[0]['pid']
        engine._port = unrelated.getsockname()[1]
        monkeypatch.setattr(plamo, '_CONNECT_TIMEOUT', .2)
        monkeypatch.setattr(plamo, '_RESPONSE_TIMEOUT', .4)
        try:
            with pytest.raises(TsError):
                engine.translate('private source text', 'en', 'zh')
            connection, _ = unrelated.accept()
            with connection:
                connection.settimeout(2)
                assert connection.recv(1) == b''
            assert_reaped(pid)
        finally:
            engine.close()
