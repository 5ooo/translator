import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def offline_project(tmp_path):
    source = Path(__file__).resolve().parents[1]
    project = tmp_path / 'offline project'
    (project / 'bin').mkdir(parents=True)
    (project / 'scripts').mkdir()
    shutil.copy2(source / 'install.sh', project / 'install.sh')
    shutil.copy2(source / 'scripts/provision.py', project / 'scripts/provision.py')
    ts = project / 'bin/ts'
    ts.write_text('#!/bin/sh\ncase "$*" in *plamo*) [ "${TS_TEST_MISSING_PLAMO:-}" != 1 ] ;; esac\n', encoding='utf-8')
    ts.chmod(0o755)
    python = project / 'bin/python'
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding='utf-8')
    python.chmod(0o755)
    tools = tmp_path / 'tools'
    tools.mkdir()
    uv = tools / 'uv'
    uv.write_text('#!/bin/sh\nprintf used > "$TS_TEST_UV_MARKER"\nexit 1\n', encoding='utf-8')
    uv.chmod(0o755)
    home = tmp_path / 'recipient home'
    home.mkdir()
    env = os.environ.copy()
    env['HOME'] = str(home)
    env['PATH'] = str(tools) + os.pathsep + env['PATH']
    env['TS_TEST_UV_MARKER'] = str(tmp_path / 'uv-used')
    return project, home, env


def test_offline_install_is_repeatable_and_does_not_invoke_uv(offline_project):
    project, home, env = offline_project
    for _ in range(2):
        result = subprocess.run([str(project / 'install.sh'), '--offline'], env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    assert (home / '.local/bin/ts').resolve() == project / 'bin/ts'
    assert not Path(env['TS_TEST_UV_MARKER']).exists()


def test_offline_install_does_not_overwrite_other_command(offline_project):
    project, home, env = offline_project
    command = home / '.local/bin/ts'
    command.parent.mkdir(parents=True)
    command.write_text('existing command', encoding='utf-8')
    result = subprocess.run([str(project / 'install.sh'), '--offline'], env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert command.read_text(encoding='utf-8') == 'existing command'


def test_offline_install_fails_if_a_model_is_unavailable(offline_project):
    project, home, env = offline_project
    env['TS_TEST_MISSING_PLAMO'] = '1'
    result = subprocess.run([str(project / 'install.sh'), '--offline'], env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert not (home / '.local/bin/ts').exists()
    assert not Path(env['TS_TEST_UV_MARKER']).exists()
