import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CHECK = Path(__file__).resolve().parents[1] / 'scripts/check-python-deps.py'


def dist(directory, name, version, *, direct=None):
    path = directory / f'{name.replace("-", "_")}-{version}.dist-info'
    path.mkdir(parents=True)
    (path / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')
    if direct is not None:
        (path / 'direct_url.json').write_text(json.dumps(direct))
    return path


@pytest.fixture
def environment(tmp_path):
    project = tmp_path / 'project with spaces'
    project.mkdir()
    (project / 'pyproject.toml').write_text('''[project]
name = "ts-check-example"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["sample-dep>=1,<2"]
[project.optional-dependencies]
test = ["sample-test>=2,<3"]
''')
    (project / 'requirements.lock').write_text('sample-dep==1.5\nsample-test==2.3\n')
    packages = tmp_path / 'site'
    packages.mkdir()
    project_metadata = dist(packages, 'ts-check-example', '0.1.0', direct={
        'url': project.as_uri(), 'dir_info': {'editable': True},
    })
    with (project_metadata / 'METADATA').open('a') as file:
        file.write('Requires-Dist: sample-dep>=1,<2\n')
        file.write('Requires-Dist: sample-test>=2,<3; extra == "test"\n')
    dist(packages, 'sample-dep', '1.5')
    dist(packages, 'sample-test', '2.3')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(packages)
    env['PYTHONNOUSERSITE'] = '1'
    return project, project_metadata, env


def check(project, env):
    return subprocess.run([sys.executable, str(CHECK), str(project)], env=env, capture_output=True, text=True)


def test_complete_matching_environment_is_reusable(environment):
    project, _, env = environment
    assert check(project, env).returncode == 0


def test_changed_lock_requires_install(environment):
    project, _, env = environment
    (project / 'requirements.lock').write_text('sample-dep==1.6\nsample-test==2.3\n')
    assert check(project, env).returncode != 0


def test_missing_dependency_requires_install(environment):
    project, _, env = environment
    (project / 'requirements.lock').write_text('sample-dep==1.5\nmissing-dep==4.0\n')
    assert check(project, env).returncode != 0


def test_changed_project_requirements_require_install(environment):
    project, _, env = environment
    config = project / 'pyproject.toml'
    config.write_text(config.read_text().replace('sample-dep>=1,<2', 'sample-dep>=2,<3'))
    assert check(project, env).returncode != 0


def test_stale_project_metadata_requires_install(environment):
    project, metadata, env = environment
    path = metadata / 'METADATA'
    path.write_text(path.read_text().replace('Requires-Dist: sample-dep>=1,<2\n', ''))
    assert check(project, env).returncode != 0


def test_different_editable_checkout_requires_install(environment, tmp_path):
    project, metadata, env = environment
    (metadata / 'direct_url.json').write_text(json.dumps({
        'url': tmp_path.as_uri(), 'dir_info': {'editable': True},
    }))
    assert check(project, env).returncode != 0


def test_unrecognized_lock_entry_requires_install(environment):
    project, _, env = environment
    (project / 'requirements.lock').write_text('sample-dep>=1\n')
    assert check(project, env).returncode != 0
