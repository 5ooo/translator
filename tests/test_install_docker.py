import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('install_docker', SCRIPTS / 'install-docker.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
finally:
    sys.path.pop(0)


def prepared(monkeypatch, tmp_path):
    monkeypatch.delenv('TS_DOCKER_DEBUG', raising=False)
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    config_path = tmp_path / 'resident.json'
    config_path.write_text('old configuration')
    monkeypatch.setattr(installer, 'service_config_path', lambda: config_path)
    monkeypatch.setattr(installer, 'docker', lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(installer, 'host_paths', lambda: {})
    monkeypatch.setattr(installer, 'host_bindings', lambda: {'model':'x'})
    monkeypatch.setattr(installer, 'default_model', lambda: 'plamo')
    monkeypatch.setattr(installer, 'source_digest', lambda: 'd'*64)
    monkeypatch.setattr(installer, 'rootless', lambda: False)
    monkeypatch.setattr(installer, 'can_try_nvidia', lambda paths: False)
    monkeypatch.setattr(installer, 'build_image', lambda instance: f'image:{instance}')


def test_failed_candidate_does_not_replace_or_stop_old_service(monkeypatch, tmp_path):
    prepared(monkeypatch, tmp_path)
    old = {'instance':'b'*32, 'root':str(tmp_path)}
    monkeypatch.setattr(installer, 'existing_config', lambda: old)
    events = []
    monkeypatch.setattr(installer, 'create_container', lambda config, paths, **kw: events.append(('create', config['instance'])))
    def fail(_config): raise RuntimeError('warmup failed')
    monkeypatch.setattr(installer, 'wait_ready', fail)
    monkeypatch.setattr(installer, 'write_config', lambda config, expected: events.append(('publish', config['instance'])))
    monkeypatch.setattr(installer, 'remove_container', lambda config: events.append(('remove', config['instance'])))
    monkeypatch.setattr(installer, 'remove_image', lambda config: events.append(('image', config['instance'])))
    with pytest.raises(RuntimeError, match='warmup failed'):
        installer.install()
    assert not any(action == 'publish' for action, value in events)
    assert not any(value == old['instance'] for action, value in events)


def test_replacement_is_published_only_after_ready(monkeypatch, tmp_path):
    prepared(monkeypatch, tmp_path)
    old = {'instance':'b'*32, 'root':str(tmp_path)}
    monkeypatch.setattr(installer, 'existing_config', lambda: old)
    events = []
    def create(config, paths, **kw):
        config.update(device='cpu',container_name='ours')
        events.append('create')
    monkeypatch.setattr(installer, 'create_container', create)
    monkeypatch.setattr(installer, 'wait_ready', lambda config: events.append('ready'))
    monkeypatch.setattr(installer, 'write_config', lambda config, expected: events.append('publish'))
    monkeypatch.setattr(installer, 'remove_container', lambda config: events.append('remove-old'))
    monkeypatch.setattr(installer, 'remove_image', lambda config: events.append('remove-image'))
    installer.install()
    assert events == ['create', 'ready', 'publish', 'remove-old', 'remove-image']


def test_unowned_container_is_not_removed_or_socket_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    instance = 'a'*32
    directory = tmp_path / '.runtime/docker' / instance
    directory.mkdir(parents=True)
    marker = directory / 'keep'
    marker.write_text('user content')
    calls = []
    def fake_docker(*args, **kwargs):
        calls.append(args)
        value = 'c'*64 + '\n' if args[0] == 'ps' else 'different-owner\n'
        return SimpleNamespace(returncode=0, stdout=value, stderr='')
    monkeypatch.setattr(installer, 'docker', fake_docker)
    with pytest.raises(RuntimeError, match='不属于本项目'):
        installer.remove_container({'instance':instance, 'container_id':'c'*64, 'directory_owned':True})
    assert marker.read_text() == 'user content'
    assert not any(args[:2] == ('rm','-f') for args in calls)


def test_bind_mount_quotes_commas(tmp_path):
    text = installer.mount(tmp_path / 'path,with,commas', '/models/argos')
    assert '"source=' in text and 'readonly' in text


@pytest.mark.parametrize('debug', [False, True])
def test_gpu_failure_retries_cpu_before_publishing(monkeypatch, tmp_path, capsys, debug):
    prepared(monkeypatch, tmp_path)
    if debug:
        monkeypatch.setenv('TS_DOCKER_DEBUG', '1')
    monkeypatch.setattr(installer, 'existing_config', lambda: None)
    monkeypatch.setattr(installer, 'can_try_nvidia', lambda paths: True)
    events = []
    def create(config, paths, *, gpu, is_rootless):
        events.append('gpu' if gpu else 'cpu')
        if gpu: raise RuntimeError('gpu unavailable')
        config.update(device='cpu', container_name='ours')
    monkeypatch.setattr(installer, 'create_container', create)
    monkeypatch.setattr(installer, 'wait_ready', lambda config: events.append('ready'))
    monkeypatch.setattr(installer, 'write_config', lambda config, expected: events.append('publish'))
    monkeypatch.setattr(installer, 'remove_container', lambda config: events.append('remove-failed'))
    installer.install()
    assert events == ['gpu', 'remove-failed', 'cpu', 'ready', 'publish']
    output = capsys.readouterr()
    assert output.out == 'Docker 常驻服务：CPU（显卡加速未启用）\n'
    assert output.err == ('显卡启动详情：gpu unavailable\n' if debug else '')


def test_existing_directory_is_not_removed_when_creation_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    instance = 'a'*32
    directory = tmp_path / '.runtime/docker' / instance
    directory.mkdir(parents=True)
    installer.remove_container({'instance':instance})
    assert directory.is_dir()


def test_nvidia_must_actually_be_used_by_container_process(monkeypatch):
    config = {'container_id':'a'*64}
    monkeypatch.setattr(installer, 'request', lambda *args, **kwargs: {'text':'网络已就绪'})
    monkeypatch.setattr(installer, 'docker', lambda *args, **kwargs: SimpleNamespace(stdout='PID COMMAND\n123 llama-server\n'))
    monkeypatch.setattr(installer.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout='123, 542\n'))
    installer.confirm_nvidia(config)
    monkeypatch.setattr(installer.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout='999, 542\n'))
    with pytest.raises(RuntimeError, match='未检测到'):
        installer.confirm_nvidia(config)


def test_existing_unrelated_config_is_not_overwritten(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    path = tmp_path / 'resident.json'
    contents = '{"root": "' + str(tmp_path) + '", "instance": "' + 'a'*32 + '"}'
    path.write_text(contents)
    monkeypatch.setattr(installer, 'service_config_path', lambda: path)
    with pytest.raises(RuntimeError, match='未覆盖'):
        installer.existing_config()
    assert path.read_text() == contents


def test_config_write_refuses_concurrent_changes(monkeypatch, tmp_path):
    path = tmp_path / 'resident.json'
    path.write_text('user content')
    monkeypatch.setattr(installer, 'service_config_path', lambda: path)
    with pytest.raises(RuntimeError, match='未覆盖'):
        installer.write_config({'instance':'a'*32}, None)
    assert path.read_text() == 'user content'
    with pytest.raises(RuntimeError, match='未覆盖'):
        installer.write_config({'instance':'a'*32}, b'older content')
    assert path.read_text() == 'user content'


def test_local_switch_keeps_config_when_docker_is_unavailable(monkeypatch, tmp_path):
    path = tmp_path / 'resident.json'
    path.write_text('current configuration')
    monkeypatch.setattr(installer, 'service_config_path', lambda: path)
    monkeypatch.setattr(installer, 'existing_config', lambda: {'instance':'a'*32})
    def offline(*_args, **_kwargs):
        raise RuntimeError('Docker 服务不可用')
    monkeypatch.setattr(installer, 'docker', offline)
    with pytest.raises(RuntimeError, match='Docker 服务不可用'):
        installer.disable()
    assert path.read_text() == 'current configuration'


def test_local_switch_keeps_config_if_container_lookup_fails(monkeypatch, tmp_path):
    path = tmp_path / 'resident.json'
    path.write_text('current configuration')
    monkeypatch.setattr(installer, 'service_config_path', lambda: path)
    monkeypatch.setattr(installer, 'existing_config',
                        lambda: {'instance':'a'*32, 'container_id':'b'*64})
    def docker(*args, **kwargs):
        if args[0] == 'info':
            return SimpleNamespace(stdout='28.5.1', returncode=0)
        raise RuntimeError('Docker 服务中断')
    monkeypatch.setattr(installer, 'docker', docker)
    with pytest.raises(RuntimeError, match='Docker 服务中断'):
        installer.disable()
    assert path.read_text() == 'current configuration'
