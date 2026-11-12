import hashlib
import importlib.util
import io
from pathlib import Path
import urllib.error

import pytest

spec = importlib.util.spec_from_file_location('ts_provision', Path(__file__).parents[1] / 'scripts/provision.py')
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(provision, 'ROOT', root)
    monkeypatch.setattr(provision, 'RUNTIME', root / '.runtime')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    (root / 'bin').mkdir()
    (root / 'bin/ts').write_text('launcher')
    return root, home


def test_command_link_is_idempotent(installation):
    root, home = installation
    provision.install_command()
    provision.install_command()
    assert (home / '.local/bin/ts').resolve() == root / 'bin/ts'


def test_command_install_never_overwrites_other_file(installation):
    _, home = installation
    destination = home / '.local/bin/ts'
    destination.parent.mkdir(parents=True)
    destination.write_text('existing user command')
    with pytest.raises(RuntimeError, match='未覆盖'):
        provision.install_command()
    assert destination.read_text() == 'existing user command'


def test_verified_cached_model_works_without_network(installation, monkeypatch):
    root, _ = installation
    cache = root / '.runtime/downloads'
    cache.mkdir(parents=True)
    path = cache / 'test.argosmodel'
    path.write_bytes(b'verified model')
    model = {'filename': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    def denied(*args, **kwargs):
        pytest.fail('缓存有效时不应联网')
    monkeypatch.setattr(provision.urllib.request, 'urlopen', denied)
    assert provision.verified_download(model).read_bytes() == b'verified model'


def test_wrong_model_hash_is_rejected_and_partial_removed(installation, monkeypatch):
    root, _ = installation
    model = {'from': 'en', 'to': 'zh', 'filename': 'bad.argosmodel',
             'sha256': hashlib.sha256(b'expected').hexdigest(), 'urls': ['https://example.invalid/model']}
    monkeypatch.setattr(provision.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'corrupt'))
    with pytest.raises(RuntimeError, match='SHA256'):
        provision.verified_download(model)
    assert not (root / '.runtime/downloads/bad.argosmodel').exists()
    assert not (root / '.runtime/downloads/bad.part').exists()
