import importlib.util
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    'package_offline', Path(__file__).resolve().parents[1] / 'scripts/package-offline.py'
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


@pytest.fixture
def small_bundle(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'README.md').write_text('usage', encoding='utf-8')
    (root / '.tags').write_text('private data', encoding='utf-8')
    (root / '.runtime/config').mkdir(parents=True)
    (root / '.runtime/config/private.json').write_text('private config', encoding='utf-8')
    venv = root / '.venv-uv'
    site = venv / 'lib/python3.12/site-packages'
    site.mkdir(parents=True)
    (venv / 'pyvenv.cfg').write_text('home = /old/project/python/bin\nversion_info = 3.12.12\n', encoding='utf-8')
    (site / '__editable__.ts_offline-0.1.0.pth').write_text('/old/project/src\n', encoding='utf-8')
    dist_info = site / 'ts_offline-0.1.0.dist-info'
    dist_info.mkdir()
    (dist_info / 'direct_url.json').write_text('{"url":"file:///old/project"}', encoding='utf-8')
    monkeypatch.setattr(package, 'ROOT', root)
    monkeypatch.setattr(package, 'inputs', lambda: ([root / 'README.md', venv / 'lib'], root / 'python', root / 'runner'))
    monkeypatch.setattr(package, 'native_libraries', lambda *_: {})
    monkeypatch.setattr(package, 'native_licenses', lambda *_: {})
    return root, tmp_path / 'ts-offline.tar.gz'


def test_archive_omits_personal_files_and_uses_movable_paths(small_bundle):
    _, output = small_bundle
    package.build(output)
    with tarfile.open(output, 'r:gz') as archive:
        names = archive.getnames()
        assert 'ts/README.md' in names
        assert not any('.tags' in name or '/config/' in name or name.endswith('direct_url.json') for name in names)
        cfg = archive.extractfile('ts/.venv-uv/pyvenv.cfg').read().decode()
        pth = archive.extractfile('ts/.venv-uv/lib/python3.12/site-packages/__editable__.ts_offline-0.1.0.pth').read().decode()
        assert '/old/project' not in cfg
        assert pth == '../../../../src\n'


def test_archive_creation_never_overwrites_existing_file(small_bundle):
    _, output = small_bundle
    output.write_bytes(b'existing file')
    with pytest.raises(RuntimeError, match='未覆盖'):
        package.build(output)
    assert output.read_bytes() == b'existing file'


def test_native_libraries_can_be_reused_from_path_with_spaces(tmp_path, monkeypatch):
    root = tmp_path / 'unpacked offline package'
    vendor = root / '.runtime/vendor/lib'
    vendor.mkdir(parents=True)
    library = vendor / 'libexample.so.1'
    library.write_bytes(b'library')
    monkeypatch.setattr(package, 'ROOT', root)
    monkeypatch.setattr(package.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=f'libexample.so.1 => {library} (0x00000000001)\n', stderr=''
    ))
    assert package.native_libraries(root / 'python', root / 'runner') == {'libexample.so.1': library}
