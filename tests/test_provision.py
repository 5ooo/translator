import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import sys
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
    monkeypatch.setenv('PATH', str(home / '.local/bin'))
    (root / 'bin').mkdir()
    (root / 'bin/ts').write_text('launcher')
    return root, home


def test_command_link_is_idempotent(installation):
    root, home = installation
    provision.install_command()
    provision.install_command()
    assert (home / '.local/bin/ts').resolve() == root / 'bin/ts'


def test_command_uses_home_bin_when_it_is_in_path(installation, monkeypatch):
    root, home = installation
    user_bin = home / 'bin'
    user_bin.mkdir()
    launcher = root / 'bin/ts'
    launcher.write_text('#!/bin/sh\nprintf "translator started\\n"\n')
    launcher.chmod(0o755)
    monkeypatch.setenv('PATH', str(user_bin))

    provision.install_command()

    assert shutil.which('ts') == str(user_bin / 'ts')
    assert subprocess.run(['ts'], capture_output=True, text=True, check=True).stdout == 'translator started\n'


def test_command_is_found_when_local_bin_is_not_in_path(installation, tmp_path, monkeypatch):
    root, _ = installation
    system_bin = tmp_path / 'usr/local/bin'
    system_bin.mkdir(parents=True)
    launcher = root / 'bin/ts'
    launcher.write_text('#!/bin/sh\nprintf "translator started\\n"\n')
    launcher.chmod(0o755)
    monkeypatch.setenv('PATH', str(system_bin))
    monkeypatch.setattr(provision, 'SYSTEM_BIN', system_bin, raising=False)

    provision.install_command()

    assert shutil.which('ts') == str(system_bin / 'ts')
    result = subprocess.run(['ts'], capture_output=True, text=True, check=True)
    assert result.stdout == 'translator started\n'


def test_unwritable_user_bin_falls_back_to_system_bin(installation, tmp_path, monkeypatch):
    root, home = installation
    user_bin = home / '.local/bin'
    system_bin = tmp_path / 'usr/local/bin'
    user_bin.mkdir(parents=True)
    system_bin.mkdir(parents=True)
    monkeypatch.setenv('PATH', f'{user_bin}:{system_bin}')
    monkeypatch.setattr(provision, 'SYSTEM_BIN', system_bin)
    symlink_to = Path.symlink_to

    def deny_user_link(path, target, *args, **kwargs):
        if path == user_bin / 'ts':
            raise PermissionError('user directory is read-only')
        return symlink_to(path, target, *args, **kwargs)

    monkeypatch.setattr(Path, 'symlink_to', deny_user_link)
    provision.install_command()

    assert (system_bin / 'ts').resolve() == root / 'bin/ts'
    assert not (user_bin / 'ts').exists()


def test_existing_command_in_path_is_not_overwritten(installation, tmp_path, monkeypatch):
    root, _ = installation
    system_bin = tmp_path / 'usr/local/bin'
    system_bin.mkdir(parents=True)
    existing = system_bin / 'ts'
    existing.write_text('#!/bin/sh\nprintf "other command\\n"\n')
    existing.chmod(0o755)
    monkeypatch.setenv('PATH', str(system_bin))
    monkeypatch.setattr(provision, 'SYSTEM_BIN', system_bin)

    with pytest.raises(RuntimeError, match='未覆盖'):
        provision.install_command()

    assert subprocess.run(['ts'], capture_output=True, text=True, check=True).stdout == 'other command\n'
    assert not (root / '.runtime/system/usr/bin/ts').exists()


def test_system_bin_permission_uses_sudo_without_path_changes(installation, tmp_path, monkeypatch):
    root, _ = installation
    system_bin = tmp_path / 'usr/local/bin'
    tools = tmp_path / 'tools'
    system_bin.mkdir(parents=True)
    tools.mkdir()
    launcher = root / 'bin/ts'
    launcher.write_text('#!/bin/sh\nprintf "translator started\\n"\n')
    launcher.chmod(0o755)
    sudo = tools / 'sudo'
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    command_path = f'{system_bin}:{tools}'
    monkeypatch.setenv('PATH', command_path)
    monkeypatch.setattr(provision, 'SYSTEM_BIN', system_bin)
    symlink_to = Path.symlink_to

    def deny_system_link(path, target, *args, **kwargs):
        if path == system_bin / 'ts':
            raise PermissionError('administrator required')
        return symlink_to(path, target, *args, **kwargs)

    monkeypatch.setattr(Path, 'symlink_to', deny_system_link)
    provision.install_command()

    assert shutil.which('ts') == str(system_bin / 'ts')
    assert subprocess.run(['ts'], capture_output=True, text=True, check=True).stdout == 'translator started\n'
    assert provision.os.environ['PATH'] == command_path


def test_sudo_does_not_replace_a_command_created_during_install(installation, tmp_path, monkeypatch):
    _, _ = installation
    system_bin = tmp_path / 'usr/local/bin'
    tools = tmp_path / 'tools'
    system_bin.mkdir(parents=True)
    tools.mkdir()
    destination = system_bin / 'ts'
    sudo = tools / 'sudo'
    sudo.write_text('#!/bin/sh\nprintf "other command" > "$TS_TEST_DESTINATION"\nexec "$@"\n')
    sudo.chmod(0o755)
    monkeypatch.setenv('PATH', f'{system_bin}:{tools}')
    monkeypatch.setenv('TS_TEST_DESTINATION', str(destination))
    monkeypatch.setattr(provision, 'SYSTEM_BIN', system_bin)

    def deny_link(*args, **kwargs):
        raise PermissionError('administrator required')

    monkeypatch.setattr(Path, 'symlink_to', deny_link)
    with pytest.raises(RuntimeError, match='未覆盖'):
        provision.install_command()

    assert destination.read_text() == 'other command'


def test_system_bin_permission_without_sudo_reports_failure(installation, tmp_path, monkeypatch):
    _, _ = installation
    system_bin = tmp_path / 'usr/local/bin'
    system_bin.mkdir(parents=True)
    monkeypatch.setenv('PATH', str(system_bin))
    monkeypatch.setattr(provision, 'SYSTEM_BIN', system_bin)
    def deny_link(*args, **kwargs):
        raise PermissionError('administrator required')

    monkeypatch.setattr(Path, 'symlink_to', deny_link)

    with pytest.raises(RuntimeError, match='管理员权限'):
        provision.install_command()

    assert not (system_bin / 'ts').exists()


def test_no_supported_command_directory_reports_failure(installation, tmp_path, monkeypatch):
    _, home = installation
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    monkeypatch.setenv('PATH', str(unrelated))
    monkeypatch.setattr(provision, 'SYSTEM_BIN', tmp_path / 'usr/local/bin')

    with pytest.raises(RuntimeError, match='没有可用的命令目录'):
        provision.install_command()

    assert not (home / '.local/bin/ts').exists()


def test_main_uses_the_calling_shell_path(installation, tmp_path, monkeypatch):
    root, home = installation
    system_bin = tmp_path / 'usr/local/bin'
    system_bin.mkdir(parents=True)
    runtime_system = home / 'runtime/system'
    injected_bin = runtime_system / 'usr/bin'
    injected_bin.mkdir(parents=True)
    launcher = root / 'bin/ts'
    launcher.write_text('#!/bin/sh\nprintf "translator started\\n"\n')
    launcher.chmod(0o755)
    monkeypatch.setenv('PATH', str(system_bin))
    monkeypatch.setenv('LD_LIBRARY_PATH', '')
    for name in ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'ARGOS_PACKAGES_DIR'):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setattr(provision, 'SYSTEM_BIN', system_bin)
    monkeypatch.setattr(provision, 'SYSTEM', runtime_system)
    monkeypatch.setattr(provision, 'install_native', lambda: None)
    monkeypatch.setattr(provision, 'install_models', lambda: None)

    provision.main()

    assert (system_bin / 'ts').resolve() == launcher
    assert not (injected_bin / 'ts').exists()


def test_link_only_option_is_rejected():
    script = Path(__file__).parents[1] / 'scripts/provision.py'
    result = subprocess.run([sys.executable, str(script), '--link-only'], capture_output=True, text=True)
    assert result.returncode == 2


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
