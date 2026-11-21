import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tarfile

import pytest


path = Path(__file__).resolve().parents[1] / 'scripts/install-plamo.py'
spec = importlib.util.spec_from_file_location('install_plamo', path)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def sources(tmp_path, monkeypatch):
    model = tmp_path / 'source.gguf'
    model.write_bytes(b'known test model')
    archive = tmp_path / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        root = tarfile.TarInfo('llama-b12110')
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        for name, data in [('llama-server', b'executable'), ('libsample.so.0', b'library')]:
            item = tarfile.TarInfo('llama-b12110/' + name)
            item.mode = 0o755
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
        link = tarfile.TarInfo('llama-b12110/libsample.so')
        link.type = tarfile.SYMTYPE
        link.linkname = 'libsample.so.0'
        tar.addfile(link)
    monkeypatch.setattr(installer, 'ROOT', tmp_path / 'project')
    monkeypatch.setattr(installer, 'MODEL_SHA256', hashlib.sha256(model.read_bytes()).hexdigest())
    monkeypatch.setattr(installer, 'RUNTIME_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    monkeypatch.setenv('TS_PLAMO_MODEL', str(tmp_path / 'models/plamo.gguf'))
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('unexpected network'))
    return model, archive


def test_offline_install_is_idempotent(sources):
    model, archive = sources
    destination = installer.install_model(model)
    runtime = installer.install_runtime(archive)
    assert destination.read_bytes() == model.read_bytes()
    assert (runtime / 'llama-server').read_bytes() == b'executable'
    assert os.access(runtime / 'llama-server', os.X_OK)
    assert (runtime / 'libsample.so').read_bytes() == b'library'
    assert installer.install_model(model) == destination
    assert installer.install_runtime(archive) == runtime


def test_offline_install_defaults_to_q4_model(sources, monkeypatch, tmp_path):
    model, _ = sources
    monkeypatch.delenv('TS_PLAMO_MODEL')
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    assert installer.main(['--model-file', str(model), '--model-only']) == 0
    target = tmp_path / 'project/.runtime/data/ts/models/plamo3/plamo-3-translate-0.8b-Q4_K_M.gguf'
    assert target.read_bytes() == model.read_bytes()


def test_offline_install_can_include_vulkan(sources, monkeypatch):
    model, archive = sources
    monkeypatch.setattr(installer, 'VULKAN_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    assert installer.main(['--model-file', str(model), '--runtime-archive', str(archive),
                           '--vulkan-archive', str(archive)]) == 0
    assert (installer.runtime_destination('cpu') / 'llama-server').is_file()
    assert (installer.runtime_destination('vulkan') / 'llama-server').is_file()


def test_existing_different_model_is_never_overwritten(sources):
    model, _ = sources
    target = installer.model_destination()
    target.parent.mkdir(parents=True)
    target.write_bytes(b'user data')
    with pytest.raises(RuntimeError, match='未覆盖'):
        installer.install_model(model)
    assert target.read_bytes() == b'user data'


def test_wrong_model_digest_leaves_no_installed_model(sources):
    model, _ = sources
    model.write_bytes(b'wrong')
    with pytest.raises(RuntimeError, match='SHA256'):
        installer.install_model(model)
    assert not installer.model_destination().exists()
    assert list(installer.model_destination().parent.iterdir()) == []


def test_interrupted_download_retries_after_removing_partial_file(tmp_path, monkeypatch):
    data = b'complete model data'
    attempts = []

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell() > 0:
                raise OSError('connection interrupted')
            return super().read(3)

    def open_url(*args, **kwargs):
        attempts.append(1)
        return Interrupted(data) if len(attempts) == 1 else io.BytesIO(data)

    monkeypatch.setattr(installer.urllib.request, 'urlopen', open_url)
    target = tmp_path / 'model'
    installer._fetch(None, 'https://example.invalid/model', target, hashlib.sha256(data).hexdigest())
    assert target.read_bytes() == data
    assert len(attempts) == 2


def test_failed_python_download_uses_curl_and_checks_digest(tmp_path, monkeypatch):
    data = b'complete runtime data'
    target = tmp_path / 'runtime'

    def unavailable(*args, **kwargs):
        raise OSError('TLS connection failed')

    def curl(command, *, check, timeout):
        assert command[0] == 'curl'
        assert not target.exists()
        target.write_bytes(data)

    monkeypatch.setattr(installer.urllib.request, 'urlopen', unavailable)
    monkeypatch.setattr(installer.shutil, 'which', lambda name: '/usr/bin/curl' if name == 'curl' else None)
    monkeypatch.setattr(installer.subprocess, 'run', curl)
    installer._fetch(None, 'https://example.invalid/runtime', target, hashlib.sha256(data).hexdigest())
    assert target.read_bytes() == data


def test_failed_download_without_external_tools_reports_error(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('TLS connection failed')

    monkeypatch.setattr(installer.urllib.request, 'urlopen', unavailable)
    monkeypatch.setattr(installer.shutil, 'which', lambda name: None)
    target = tmp_path / 'runtime'
    with pytest.raises(RuntimeError, match='下载失败'):
        installer._fetch(None, 'https://example.invalid/runtime', target, 'unused')
    assert not target.exists()


def test_failed_python_download_uses_wget_without_curl(tmp_path, monkeypatch):
    data = b'complete runtime data'
    target = tmp_path / 'runtime'

    def unavailable(*args, **kwargs):
        raise OSError('TLS connection failed')

    def wget(command, *, check, timeout):
        assert command[0] == 'wget'
        target.write_bytes(data)

    monkeypatch.setattr(installer.urllib.request, 'urlopen', unavailable)
    monkeypatch.setattr(installer.shutil, 'which', lambda name: '/usr/bin/wget' if name == 'wget' else None)
    monkeypatch.setattr(installer.subprocess, 'run', wget)
    installer._fetch(None, 'https://example.invalid/runtime', target, hashlib.sha256(data).hexdigest())
    assert target.read_bytes() == data


def test_failed_curl_download_falls_back_to_wget(tmp_path, monkeypatch):
    data = b'complete runtime data'
    target = tmp_path / 'runtime'
    commands = []

    def unavailable(*args, **kwargs):
        raise OSError('TLS connection failed')

    def download(command, *, check, timeout):
        commands.append(command[0])
        if command[0] == 'curl':
            target.write_bytes(b'partial')
            raise installer.subprocess.CalledProcessError(1, command)
        assert not target.exists()
        target.write_bytes(data)

    monkeypatch.setattr(installer.urllib.request, 'urlopen', unavailable)
    monkeypatch.setattr(installer.shutil, 'which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr(installer.subprocess, 'run', download)
    installer._fetch(None, 'https://example.invalid/runtime', target, hashlib.sha256(data).hexdigest())
    assert target.read_bytes() == data
    assert commands == ['curl', 'wget']


def test_modified_runtime_is_not_replaced(sources):
    _, archive = sources
    runtime = installer.install_runtime(archive)
    (runtime / 'libsample.so.0').write_bytes(b'user data')
    with pytest.raises(RuntimeError, match='未覆盖'):
        installer.install_runtime(archive)
    assert (runtime / 'libsample.so.0').read_bytes() == b'user data'


def test_runtime_install_does_not_overwrite_a_racing_writer(sources, monkeypatch):
    _, archive = sources
    real_publish = installer._publish_directory
    def race(staged, target):
        target.mkdir()
        (target / 'user-data').write_bytes(b'keep')
        return real_publish(staged, target)
    monkeypatch.setattr(installer, '_publish_directory', race)
    with pytest.raises(RuntimeError, match='未覆盖'):
        installer.install_runtime(archive)
    assert (installer.runtime_destination() / 'user-data').read_bytes() == b'keep'


def test_unsafe_archive_link_is_rejected(sources, tmp_path, monkeypatch):
    _, _ = sources
    archive = tmp_path / 'unsafe.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        link = tarfile.TarInfo('llama-b12110/libescape.so')
        link.type = tarfile.SYMTYPE
        link.linkname = '../../outside'
        tar.addfile(link)
    monkeypatch.setattr(installer, 'RUNTIME_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(RuntimeError, match='不安全'):
        installer.install_runtime(archive)
    assert not installer.runtime_destination().exists()
