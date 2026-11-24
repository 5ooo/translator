import contextlib
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ts import cli, resident
from ts.errors import TsError


class FakeRuntime:
    def __init__(self):
        self.engines = {}
        self.ocr_engines = {}
        self.ocr_ready = set()

    def warm(self, model):
        self.engines[model] = True
        self.ocr_ready.add(resident.MODELS[model].ocr_variant)

    def translate(self, text, model):
        self.engines[model] = True
        return f'{model}:{text}'

    def ocr(self, data, model):
        self.ocr_engines[resident.MODELS[model].ocr_variant] = True
        self.ocr_ready.add(resident.MODELS[model].ocr_variant)
        return f'{model}:{hashlib.sha256(data).hexdigest()}'

    def close(self):
        pass


def serve_fake(path, instance):
    resident.Runtime = FakeRuntime
    resident.source_digest = lambda *_: 'b' * 64
    resident.serve(path, instance, 'plamo')


@pytest.fixture
def running_service(tmp_path, monkeypatch):
    instance = 'a' * 32
    directory = tmp_path / '.runtime/docker' / instance
    directory.mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(resident, 'ROOT', tmp_path)
    monkeypatch.setattr(resident, 'source_digest', lambda *_: 'b' * 64)
    monkeypatch.setattr(resident, 'host_bindings', lambda: {'model': '/model'})
    monkeypatch.setattr(resident, 'Runtime', FakeRuntime)
    config = {'protocol': resident.PROTOCOL, 'root': str(tmp_path), 'instance': instance, 'source_digest': 'b' * 64}
    process = multiprocessing.get_context('spawn').Process(
        target=serve_fake, args=(directory / 'service.sock', instance))
    process.start()
    try:
        deadline = time.monotonic() + 5
        while not (directory / 'service.sock').exists():
            if not process.is_alive() or time.monotonic() > deadline:
                pytest.fail('service did not start')
            time.sleep(.02)
        yield config, directory
    finally:
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
    assert not (directory / 'service.sock').exists()


def test_service_reuses_models_and_preserves_per_request_selection(running_service):
    config, _ = running_service
    assert resident.request(config, 'ping')['loaded'] == ['plamo']
    assert resident.request(config, 'translate', model='plamo', text='Hello')['text'] == 'plamo:Hello'
    assert resident.request(config, 'translate', model='argos', text='你好')['text'] == 'argos:你好'
    assert resident.request(config, 'ping')['loaded'] == ['argos', 'plamo']


def test_service_receives_binary_image_and_retains_both_ocr_models(running_service):
    config, _ = running_service
    image = b'\x89PNG\r\n\0\xff\n' + b'image content' * 5000
    digest = hashlib.sha256(image).hexdigest()
    assert resident.request(config, 'ocr', model='argos', image=image)['text'] == f'argos:{digest}'
    assert resident.request(config, 'ocr', model='plamo', image=image)['text'] == f'plamo:{digest}'
    assert resident.request(config, 'ocr', model='argos', image=image)['text'] == f'argos:{digest}'
    assert resident.request(config, 'ping')['ocr_loaded'] == ['small', 'tiny']


def test_service_rejects_ocr_request_with_unknown_mode(running_service):
    config, _ = running_service
    with pytest.raises(TsError, match='无效.*OCR'):
        resident.request(config, 'ocr', model='unknown', image=b'image')


def test_service_receives_image_larger_than_text_message_limit(running_service):
    config, _ = running_service
    image = b'\0\n\xff' * (6 * 1024 * 1024)
    digest = hashlib.sha256(image).hexdigest()
    assert resident.request(config, 'ocr', model='argos', image=image)['text'] == f'argos:{digest}'


def test_concurrent_requests_are_isolated(running_service):
    config, _ = running_service
    def send(index):
        model = 'argos' if index % 2 else 'plamo'
        result = resident.request(config, 'translate', model=model, text=f'hello {index}')
        return result['text'] == f'{model}:hello {index}'
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(send, range(12)))


def test_service_rejects_bad_version_and_model(running_service):
    config, _ = running_service
    with pytest.raises(TsError, match='无效翻译请求'):
        resident.request(config, 'translate', model='not-a-model', text='hello')
    wrong = {**config, 'source_digest': 'c' * 64}
    with pytest.raises(TsError, match='版本或身份不符'):
        resident.request(wrong, 'ping')


def test_client_rejects_unsafe_socket_permissions(running_service):
    config, directory = running_service
    directory.chmod(0o755)
    try:
        with pytest.raises(TsError, match='权限不安全'):
            resident.request(config, 'ping')
    finally:
        directory.chmod(0o700)


def test_service_does_not_replace_regular_files(tmp_path):
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    target = directory / 'service.sock'
    target.write_text('do not overwrite')
    with pytest.raises(TsError, match='未覆盖'):
        resident._prepare_socket(target)
    assert target.read_text() == 'do not overwrite'


def test_service_config_rejects_moved_or_changed_project(tmp_path, monkeypatch):
    config_file = tmp_path / 'config.json'
    monkeypatch.setattr(resident, 'config_path', lambda: config_file)
    monkeypatch.setattr(resident, 'ROOT', tmp_path)
    monkeypatch.setattr(resident, 'source_digest', lambda *_: 'b' * 64)
    monkeypatch.setattr(resident, 'host_bindings', lambda: {'model': '/model'})
    path = config_file.with_name('resident.json')
    config = {'protocol': resident.PROTOCOL, 'instance': 'a'*32, 'root': str(tmp_path), 'source_digest':'b'*64,
              'host_bindings': {'model': '/model'}}
    path.write_text(json.dumps(config))
    assert resident.read_service_config() == config
    path.write_text(json.dumps({**config, 'root':'/old/project'}))
    with pytest.raises(TsError, match='项目位置已改变'):
        resident.read_service_config()
    path.write_text(json.dumps({**config, 'source_digest':'c'*64}))
    with pytest.raises(TsError, match='项目代码已更新'):
        resident.read_service_config()
    path.write_text(json.dumps({**config, 'host_bindings': {'model': '/different'}}))
    with pytest.raises(TsError, match='模型或运行器配置已改变'):
        resident.read_service_config()


def test_runtime_caches_detector_and_each_engine(monkeypatch):
    opened, closed = [], []
    class FakeEngine:
        def __init__(self, name): self.name = name
        def translate(self, text, source, target): return f'{self.name}:{text}'
    @contextlib.contextmanager
    def open_engine(name):
        opened.append(name)
        try: yield FakeEngine(name)
        finally: closed.append(name)
    monkeypatch.setattr(resident, 'Detector', lambda: lambda text: 'en')
    monkeypatch.setattr(resident, 'open_translator', open_engine)
    runtime = resident.Runtime()
    try:
        assert runtime.translate('Hello', 'plamo') == 'plamo:Hello'
        assert runtime.translate('World', 'plamo') == 'plamo:World'
        assert runtime.translate('Hello', 'argos') == 'argos:Hello'
        assert opened == ['plamo', 'argos']
    finally:
        runtime.close()
    assert set(closed) == {'plamo', 'argos'}


def test_runtime_caches_ocr_engines_per_mode(monkeypatch):
    opened = []

    class FakeOCR:
        def __init__(self, variant):
            self.variant = variant
            opened.append(variant)

        def recognize(self, data):
            return f'{self.variant}:{data.decode()}'

    monkeypatch.setattr(resident, 'OCREngine', FakeOCR)
    runtime = resident.Runtime()
    try:
        assert runtime.ocr(b'first', 'argos') == 'tiny:first'
        assert runtime.ocr(b'second', 'argos') == 'tiny:second'
        assert runtime.ocr(b'third', 'plamo') == 'small:third'
        assert runtime.ocr(b'fourth', 'argos') == 'tiny:fourth'
        assert opened == ['tiny', 'small']
    finally:
        runtime.close()


def test_runtime_keeps_ocr_engine_after_image_without_text(monkeypatch):
    created = []

    class FakeOCR:
        def __init__(self, variant):
            created.append(variant)

        def recognize(self, data):
            if data == b'empty':
                raise TsError('图片中没有识别出文字。')
            return 'recognized'

    monkeypatch.setattr(resident, 'OCREngine', FakeOCR)
    runtime = resident.Runtime()
    try:
        with pytest.raises(TsError, match='没有识别出文字'):
            runtime.ocr(b'empty', 'argos')
        assert runtime.ocr_ready == set()
        assert runtime.ocr(b'valid', 'argos') == 'recognized'
        assert runtime.ocr_ready == {'tiny'}
        assert created == ['tiny']
    finally:
        runtime.close()


def test_cli_sends_complete_text_and_selected_model(monkeypatch, capsys):
    config = {'instance': 'x'}
    calls = []
    monkeypatch.setattr(cli, 'read_service_config', lambda: config)
    def request(value, operation, **kwargs):
        calls.append((value, operation, kwargs))
        return {'text':'你好，世界。'}
    monkeypatch.setattr(cli, 'request', request)
    assert cli.main(['--model', 'plamo', '--plain', '--text', 'Hello world.']) == 0
    assert capsys.readouterr().out == '你好，世界。\n'
    assert calls == [(config, 'translate', {'model':'plamo', 'text':'Hello world.',
                                            'wait_if_starting': True})]


def test_cli_reports_disconnected_service(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'read_service_config', lambda: {'instance':'x'})
    def fail(*_args, **_kwargs): raise TsError('Docker 常驻服务不可用')
    monkeypatch.setattr(cli, 'request', fail)
    assert cli.main(['--text', 'Hello']) == 1
    output = capsys.readouterr()
    assert output.out == ''
    assert 'Docker 常驻服务不可用' in output.err


def test_client_waits_for_owned_running_container_to_warm(monkeypatch):
    attempts = []
    def once(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise resident.ServiceUnavailable('starting')
        return {'text':'你好'}
    monkeypatch.setattr(resident, '_request_once', once)
    monkeypatch.setattr(resident, '_container_running', lambda config: True)
    monkeypatch.setattr(resident.time, 'sleep', lambda _: None)
    assert resident.request({'instance':'a'*32}, 'translate', wait_if_starting=True)['text'] == '你好'
    assert len(attempts) == 3


def test_client_does_not_wait_for_stopped_container(monkeypatch):
    monkeypatch.setattr(resident, '_request_once', lambda *args, **kwargs: (_ for _ in ()).throw(resident.ServiceUnavailable('stopped')))
    monkeypatch.setattr(resident, '_container_running', lambda config: False)
    with pytest.raises(resident.ServiceUnavailable, match='stopped'):
        resident.request({'instance':'a'*32}, 'translate', wait_if_starting=True)


def test_check_reports_resident_service_failure(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'check', lambda: (True, ['本地依赖: 可用']))
    monkeypatch.setattr(cli, 'read_service_config', lambda: {'instance':'x'})
    def fail(*_args, **_kwargs): raise TsError('服务已停止')
    monkeypatch.setattr(cli, 'request', fail)
    assert cli.main(['--check']) == 1
    assert 'Docker 常驻服务: 不可用' in capsys.readouterr().out
