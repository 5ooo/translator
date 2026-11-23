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
    command.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TS_TEST_CHECKS"\nexit 0\n')
    command.chmod(0o755)
    python = project / 'bin/python'
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TS_TEST_PLAMO"\nexit 0\n')
    python.chmod(0o755)
    tools = tmp_path / 'tools'
    tools.mkdir()
    uv = tools / 'uv'
    uv.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
if args == ['--version']:
    print('uv 0.9.10')
    sys.exit(0)
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
    env['PATH'] = str(tools) + os.pathsep + '/usr/bin:/bin'
    env['TS_TEST_LOG'] = str(tmp_path / 'uv.jsonl')
    env['TS_TEST_CHECKS'] = str(tmp_path / 'checks.log')
    env['TS_TEST_PLAMO'] = str(tmp_path / 'plamo.log')
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
    assert str(project / 'scripts/install-plamo.py') in Path(env['TS_TEST_PLAMO']).read_text()
    assert Path(env['TS_TEST_CHECKS']).read_text().splitlines() == [
        '--check --model argos', '--check --model plamo',
    ]

    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    assert len([entry for entry in calls(env) if entry['args'][:2] == ['python', 'install']]) == 1


def test_offline_installer_option_is_rejected(installation):
    project, env = installation
    result = subprocess.run([str(project / 'install.sh'), '--offline'], env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert not (project / '.venv-uv').exists()
    assert not Path(env['TS_TEST_LOG']).exists()


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


def mock_uv_download(project, env, tmp_path):
    tools = Path(env['PATH'].split(os.pathsep)[0])
    template = tmp_path / 'uv-template'
    (tools / 'uv').rename(template)
    env['TS_TEST_UV_TEMPLATE'] = str(template)
    env['UV_INSTALL_DIR'] = str(tmp_path / 'unrelated-uv')
    env['CARGO_DIST_FORCE_INSTALL_DIR'] = str(tmp_path / 'unrelated-cargo')
    curl = tools / 'curl'
    curl.write_text('''#!/bin/sh
while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then shift; output="$1"; fi
    shift
done
cat > "$output" <<'EOF'
#!/bin/sh
test -z "${UV_INSTALL_DIR+x}" && test -z "${CARGO_DIST_FORCE_INSTALL_DIR+x}" || exit 1
mkdir -p "$UV_UNMANAGED_INSTALL"
cp "$TS_TEST_UV_TEMPLATE" "$UV_UNMANAGED_INSTALL/uv"
EOF
''')
    curl.chmod(0o755)
    sha = tools / 'sha256sum'
    sha.write_text('''#!/bin/sh
if [ "${TS_TEST_BAD_HASH:-}" = 1 ]; then
    printf '%064d  %s\\n' 0 "$1"
else
    printf '578d164a618b6b2825017d6dab73b00925e3895b47f22b25434b3fee2ec9f849  %s\\n' "$1"
fi
''')
    sha.chmod(0o755)


def test_installer_bootstraps_uv_and_both_models(installation, tmp_path):
    project, env = installation
    mock_uv_download(project, env, tmp_path)
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    assert (project / '.runtime/tools/uv-0.9.10/uv').is_file()
    assert str(project / 'scripts/install-plamo.py') in Path(env['TS_TEST_PLAMO']).read_text()
    assert Path(env['TS_TEST_CHECKS']).read_text().splitlines() == [
        '--check --model argos', '--check --model plamo',
    ]
    assert not Path(env['UV_INSTALL_DIR']).exists()
    assert not Path(env['CARGO_DIST_FORCE_INSTALL_DIR']).exists()
    (Path(env['PATH'].split(os.pathsep)[0]) / 'curl').unlink()
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)


def test_installer_rejects_unverified_uv_script(installation, tmp_path):
    project, env = installation
    mock_uv_download(project, env, tmp_path)
    env['TS_TEST_BAD_HASH'] = '1'
    result = subprocess.run([str(project / 'install.sh')], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'SHA256' in result.stderr
    assert not (project / '.runtime/tools/uv-0.9.10/uv').exists()
    assert not (project / '.venv-uv').exists()


def mock_wget(tools):
    wget = tools / 'wget'
    wget.write_text('''#!/bin/sh
for argument in "$@"; do
    case "$argument" in --output-document=*) output="${argument#*=}";; esac
done
cat > "$output" <<'EOF'
#!/bin/sh
mkdir -p "$UV_UNMANAGED_INSTALL"
cp "$TS_TEST_UV_TEMPLATE" "$UV_UNMANAGED_INSTALL/uv"
EOF
''')
    wget.chmod(0o755)


def test_installer_downloads_uv_with_wget_if_curl_is_unavailable(installation, tmp_path):
    project, env = installation
    mock_uv_download(project, env, tmp_path)
    tools = Path(env['PATH'].split(os.pathsep)[0])
    (tools / 'curl').unlink()
    for name in ('bash', 'sh', 'dirname', 'readlink', 'mkdir', 'rm', 'mktemp', 'env', 'cat', 'cp'):
        (tools / name).symlink_to(shutil.which(name))
    mock_wget(tools)
    env['PATH'] = str(tools)
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    assert (project / '.runtime/tools/uv-0.9.10/uv').is_file()
    assert str(project / 'scripts/install-plamo.py') in Path(env['TS_TEST_PLAMO']).read_text()


def test_installer_uses_wget_if_curl_fails(installation, tmp_path):
    project, env = installation
    mock_uv_download(project, env, tmp_path)
    tools = Path(env['PATH'].split(os.pathsep)[0])
    (tools / 'curl').write_text('#!/bin/sh\nexit 1\n')
    mock_wget(tools)
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    assert (project / '.runtime/tools/uv-0.9.10/uv').is_file()


def test_installer_uses_pinned_uv_when_system_version_differs(installation, tmp_path):
    project, env = installation
    mock_uv_download(project, env, tmp_path)
    other_uv = Path(env['PATH'].split(os.pathsep)[0]) / 'uv'
    other_uv.write_text('#!/bin/sh\nprintf "uv 0.1.0\\n"\n')
    other_uv.chmod(0o755)
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    assert (project / '.runtime/tools/uv-0.9.10/uv').is_file()


def test_installer_does_not_overwrite_existing_uv_file(installation, tmp_path):
    project, env = installation
    mock_uv_download(project, env, tmp_path)
    target = project / '.runtime/tools/uv-0.9.10/uv'
    target.parent.mkdir(parents=True)
    target.write_text('user data')
    result = subprocess.run([str(project / 'install.sh')], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert '未覆盖' in result.stderr
    assert target.read_text() == 'user data'
    assert not (project / '.venv-uv').exists()


def test_installer_docker_option_provisions_resident_service(installation):
    project, env = installation
    docker = Path(env['PATH'].split(os.pathsep)[0]) / 'docker'
    docker.write_text('#!/bin/sh\nexit 0\n')
    docker.chmod(0o755)
    subprocess.run([str(project / 'install.sh'), '--docker'], env=env, check=True, capture_output=True)
    assert str(project / 'scripts/install-docker.py') + ' install' in Path(env['TS_TEST_PLAMO']).read_text()


def test_installer_rejects_docker_mode_if_daemon_unavailable(installation):
    project, env = installation
    docker = Path(env['PATH'].split(os.pathsep)[0]) / 'docker'
    docker.write_text('#!/bin/sh\nexit 1\n')
    docker.chmod(0o755)
    result = subprocess.run([str(project / 'install.sh'), '--docker'], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'Docker 不可用' in result.stderr
    assert not (project / '.venv-uv').exists()


def test_installer_local_option_disables_resident_service(installation):
    project, env = installation
    python = project / '.venv-uv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nexit 0\n')
    python.chmod(0o755)
    subprocess.run([str(project / 'install.sh'), '--local'], env=env, check=True, capture_output=True)
    assert str(project / 'scripts/install-docker.py') + ' disable' in Path(env['TS_TEST_PLAMO']).read_text()
    assert not Path(env['TS_TEST_LOG']).exists()


def test_docker_installer_reuses_complete_python_environment_without_network(installation):
    project, env = installation
    python = project / '.venv-uv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nexit 0\n')
    python.chmod(0o755)
    tools = Path(env['PATH'].split(os.pathsep)[0])
    docker = tools / 'docker'
    docker.write_text('#!/bin/sh\nexit 0\n')
    docker.chmod(0o755)
    uv = tools / 'uv'
    text = uv.read_text()
    text = text.replace("elif args[:2] != ['pip', 'install']:",
                        "elif args[:2] == ['pip', 'install']:\n    sys.exit(17)\nelif args[:2] != ['pip', 'install']:")
    uv.write_text(text)
    result = subprocess.run([str(project / 'install.sh'), '--docker'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert str(project / 'scripts/install-docker.py') + ' install' in Path(env['TS_TEST_PLAMO']).read_text()
    assert not Path(env['TS_TEST_LOG']).exists()


def test_incomplete_python_environment_still_installs_dependencies(installation):
    project, env = installation
    python = project / '.venv-uv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\ncase "$1" in *check-python-deps.py) exit 1;; esac\nexit 0\n')
    python.chmod(0o755)
    subprocess.run([str(project / 'install.sh')], env=env, check=True, capture_output=True)
    assert any(entry['args'][:2] == ['pip', 'install'] for entry in calls(env))
