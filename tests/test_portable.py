import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_launcher_works_after_project_is_moved(tmp_path):
    original = tmp_path / 'original'
    moved = tmp_path / 'moved project'
    runtime = original / '.runtime/python/managed'
    python_bin = runtime / 'bin/python3.12'
    python_bin.parent.mkdir(parents=True)
    shutil.copy2(Path(sys._base_executable).resolve(), python_bin)
    (runtime / 'lib').mkdir()
    (runtime / 'lib/python3.12').symlink_to(Path(sys.base_prefix) / 'lib/python3.12')
    venv_bin = original / '.venv-uv/bin'
    venv_bin.mkdir(parents=True)
    (venv_bin / 'python').symlink_to('../../.runtime/python/managed/bin/python3.12')
    (original / '.venv-uv/pyvenv.cfg').write_text(f'home = {runtime}/bin\n', encoding='utf-8')
    source = original / 'src/ts'
    source.mkdir(parents=True)
    (source / '__init__.py').write_text('', encoding='utf-8')
    (source / '__main__.py').write_text('print("started from moved project")\n', encoding='utf-8')
    (original / 'bin').mkdir()
    shutil.copy2(Path(__file__).resolve().parents[1] / 'bin/ts', original / 'bin/ts')
    shutil.copy2(Path(__file__).resolve().parents[1] / 'bin/python', original / 'bin/python')
    original.rename(moved)

    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME'):
        env.pop(key, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONHASHSEED'] = '0'
    result = subprocess.run([str(moved / 'bin/ts'), '--models'], cwd=tmp_path, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'started from moved project'
