import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def installation(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    shutil.copy2(Path(__file__).resolve().parents[1] / 'install.sh', project / 'install.sh')
    (project / 'bin').mkdir()
    command = project / 'bin/ts'
    command.write_text('#!/bin/sh\nexit 0\n')
    command.chmod(0o755)
    tools = tmp_path / 'tools'
    tools.mkdir()
    uv = tools / 'uv'
    uv.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['TS_TEST_LOG'], 'a') as file:
    file.write(json.dumps({{'args': args, 'python_dir': os.environ.get('UV_PYTHON_INSTALL_DIR')}}) + '\\n')
if args[:2] == ['python', 'install']:
    if os.environ.get('TS_TEST_FAIL_PYTHON_INSTALL'):
        sys.exit(9)
    python = pathlib.Path(os.environ['UV_PYTHON_INSTALL_DIR']) / 'cpython-3.12.12-linux-x86_64-gnu/bin/python3.12'
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('#!/bin/sh\\nexit 0\\n')
    python.chmod(0o755)
elif args[:2] == ['python', 'find']:
    print(os.environ.get('TS_TEST_EXTERNAL_PYTHON') or pathlib.Path(os.environ['UV_PYTHON_INSTALL_DIR']) / 'cpython-3.12.12-linux-x86_64-gnu/bin/python3.12')
elif args[0] == 'venv':
    python = pathlib.Path(args[-1]) / 'bin/python'
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('#!/bin/sh\\nexit 0\\n')
    python.chmod(0o755)
elif args[:2] != ['pip', 'install']:
    sys.exit(2)
''')
    uv.chmod(0o755)
    env = os.environ.copy()
    env.pop('TS_PYTHON', None)
    env['PATH'] = str(tools) + os.pathsep + env['PATH']
    env['TS_TEST_LOG'] = str(tmp_path / 'uv.jsonl')
    env['UV_PYTHON_INSTALL_DIR'] = str(tmp_path / 'unrelated-python')
    return project, env


def calls(env):
    return [json.loads(line) for line in Path(env['TS_TEST_LOG']).read_text().splitlines()]


def test_installer_creates_project_local_python_and_reuses_it(installation):
    project, env = installation
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    entries = calls(env)
    python_dir = project / '.runtime/python'
    assert entries[0]['args'][:2] == ['python', 'install']
    assert '--no-bin' in entries[0]['args']
    assert entries[0]['python_dir'] == str(python_dir)
    venv = next(entry['args'] for entry in entries if entry['args'][0] == 'venv')
    assert Path(venv[venv.index('--python') + 1]).is_relative_to(python_dir)
    assert (project / '.venv-uv/bin/python').is_file()

    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    assert len([entry for entry in calls(env) if entry['args'][:2] == ['python', 'install']]) == 1


def test_installer_respects_explicit_python(installation):
    project, env = installation
    env['TS_PYTHON'] = '/custom/python'
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    entries = calls(env)
    assert not any(entry['args'][:2] == ['python', 'install'] for entry in entries)
    venv = next(entry['args'] for entry in entries if entry['args'][0] == 'venv')
    assert venv[venv.index('--python') + 1] == '/custom/python'


def test_python_install_failure_does_not_create_environment(installation):
    project, env = installation
    env['TS_TEST_FAIL_PYTHON_INSTALL'] = '1'
    result = subprocess.run([str(project / 'install.sh')], env=env, capture_output=True)
    assert result.returncode != 0
    assert not (project / '.venv-uv').exists()


def test_installer_rejects_unexpected_external_python(installation, tmp_path):
    project, env = installation
    external = tmp_path / 'external-python'
    external.write_text('external')
    env['TS_TEST_EXTERNAL_PYTHON'] = str(external)
    result = subprocess.run([str(project / 'install.sh')], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert '未找到项目内' in result.stderr
    assert not (project / '.venv-uv').exists()
