#!/usr/bin/env python3
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import runpy
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_SYSTEM_LIBS = {
    'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2',
    'librt.so.1', 'libutil.so.1', 'libresolv.so.2', 'libanl.so.1',
}


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inputs():
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('离线包仅支持在 Linux x86-64 上构建。')
    python = (ROOT / '.venv-uv/bin/python').resolve()
    if not python.is_file() or not python.is_relative_to(ROOT / '.runtime/python'):
        raise RuntimeError('离线包需要项目内的 Python 环境，请先按默认方式安装。')

    model_config = runpy.run_path(str(ROOT / 'scripts/install-plamo.py'))
    plamo_model = ROOT / '.runtime/data/ts/models/plamo3' / model_config['MODEL_NAME']
    if not plamo_model.is_file() or checksum(plamo_model) != model_config['MODEL_SHA256']:
        raise RuntimeError('PLaMo 模型缺失或校验失败。')
    cpu_runner = ROOT / '.runtime/tools' / model_config['RUNTIME_DIRECTORY']
    if not model_config['_matches_runtime'](cpu_runner, model_config['RUNTIME_SHA256']):
        raise RuntimeError('PLaMo CPU 运行器缺失或校验失败。')
    vulkan_runner = ROOT / '.runtime/tools/llama-b12110-vulkan'
    if vulkan_runner.exists() and not model_config['_matches_runtime'](vulkan_runner, model_config['VULKAN_SHA256']):
        raise RuntimeError('PLaMo Vulkan 运行器不完整。')

    specs = json.loads((ROOT / 'scripts/models.json').read_text(encoding='utf-8'))
    argos = [ROOT / '.runtime/data/argos-translate/packages' / spec['filename'].removesuffix('.argosmodel')
             for spec in specs]
    for package in argos:
        for relative in ('metadata.json', 'sentencepiece.model', 'model/model.bin'):
            if not (package / relative).is_file():
                raise RuntimeError(f'Argos 模型缺少文件：{package / relative}')

    paths = [ROOT / name for name in (
        'README.md', 'CHANGELOG.md', 'install.sh', 'pyproject.toml', 'requirements.txt',
        'requirements.lock', 'bin', 'docs', 'scripts', 'src', 'tests',
        '.runtime/python', '.runtime/system', '.venv-uv/lib', '.venv-uv/lib64',
        '.venv-uv/bin/python', '.venv-uv/bin/python3', '.venv-uv/bin/python3.12',
    )] + argos + [plamo_model, cpu_runner]
    if vulkan_runner.exists():
        paths.append(vulkan_runner)
    for path in paths:
        if not path.exists():
            raise RuntimeError(f'缺少离线包文件：{path}')
        if path.is_symlink() and (os.path.isabs(os.readlink(path)) or not path.resolve().is_relative_to(ROOT)):
            raise RuntimeError(f'离线包文件包含不可搬动的链接：{path}')
        if path.is_dir():
            for directory, folders, files in os.walk(path, followlinks=False):
                for name in folders + files:
                    child = Path(directory) / name
                    if child.is_symlink() and (os.path.isabs(os.readlink(child)) or not child.resolve().is_relative_to(ROOT)):
                        raise RuntimeError(f'离线包文件包含不可搬动的链接：{child}')
    for name in ('tesseract', 'xclip', 'wl-paste'):
        if not os.access(ROOT / '.runtime/system/usr/bin' / name, os.X_OK):
            raise RuntimeError(f'项目内缺少 {name}，无法制作包含剪贴板和 OCR 的离线包。')
    for language in ('eng', 'chi_sim'):
        data = ROOT / '.runtime/system/usr/share/tesseract-ocr/5/tessdata' / f'{language}.traineddata'
        if not data.is_file():
            raise RuntimeError(f'项目内缺少 Tesseract {language} 语言包。')
    return paths, python, cpu_runner


def native_libraries(python, cpu_runner):
    binaries = [python, cpu_runner / 'llama-server']
    binaries += [ROOT / '.runtime/system/usr/bin' / name for name in ('tesseract', 'xclip', 'wl-paste')]
    site_packages = ROOT / '.venv-uv/lib/python3.12/site-packages'
    for path in site_packages.rglob('*.so*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as source:
                if source.read(4) == b'\x7fELF':
                    binaries.append(path)
    env = os.environ.copy()
    env.pop('LD_LIBRARY_PATH', None)
    env['PATH'] = '/usr/bin:/bin'
    vendor = ROOT / '.runtime/vendor/lib'
    if vendor.is_dir():
        env['LD_LIBRARY_PATH'] = str(vendor)
    libraries = {}
    for binary in binaries:
        result = subprocess.run(['/usr/bin/ldd', str(binary)], env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'无法检查原生依赖：{binary}\n{result.stderr}')
        for line in result.stdout.splitlines():
            if 'not found' in line:
                raise RuntimeError(f'原生依赖缺失：{binary}\n{line.strip()}')
            match = re.match(r'\s*(\S+)\s+=>\s+(/.*?)\s+\(0x[0-9a-fA-F]+\)\s*$', line)
            if not match:
                continue
            name, location = match.groups()
            path = Path(location).resolve()
            if name in EXCLUDED_SYSTEM_LIBS:
                continue
            if path.is_relative_to(ROOT) and not path.is_relative_to(vendor):
                continue
            if not path.is_relative_to(ROOT) and not path.is_relative_to('/usr/lib') and not path.is_relative_to('/lib'):
                candidates = [Path('/usr/lib/x86_64-linux-gnu') / name, Path('/lib/x86_64-linux-gnu') / name]
                path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
                if path is None:
                    raise RuntimeError(f'找不到可分发的系统库：{name}')
            if name in libraries and libraries[name] != path:
                raise RuntimeError(f'同名系统库来自不同路径：{name}')
            libraries[name] = path
    return libraries


def native_licenses(libraries):
    paths = sorted({str(path) for path in libraries.values()})
    result = subprocess.run(['/usr/bin/dpkg-query', '-S', *paths], capture_output=True, text=True)
    packages = set()
    for line in result.stdout.splitlines():
        package_names, separator, _ = line.partition(': ')
        if separator:
            packages.update(name.split(':', 1)[0] for name in package_names.split(', '))
    licenses = {path.name.removesuffix('.copyright'): path
                for path in (ROOT / '.runtime/vendor/licenses').glob('*.copyright')}
    for package in sorted(packages):
        copyright_file = Path('/usr/share/doc') / package / 'copyright'
        if copyright_file.is_file():
            licenses[package] = copyright_file
    return licenses


def archive_filter(info):
    parts = Path(info.name).parts
    if '__pycache__' in parts or info.name.endswith(('.pyc', '.pyo')):
        return None
    if info.name.endswith('/direct_url.json') and 'ts_offline-' in info.name:
        return None
    if '/site-packages/__editable__.ts_offline-' in info.name and info.name.endswith('.pth'):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    return info


def add_bytes(archive, name, data):
    info = tarfile.TarInfo('ts/' + name)
    info.size = len(data)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(data))


def build(destination):
    paths, python, cpu_runner = inputs()
    libraries = native_libraries(python, cpu_runner)
    licenses = native_licenses(libraries)
    cfg = (ROOT / '.venv-uv/pyvenv.cfg').read_text(encoding='utf-8')
    cfg = ''.join(line for line in cfg.splitlines(keepends=True) if not line.strip().startswith('home ='))
    pth = list((ROOT / '.venv-uv/lib/python3.12/site-packages').glob('__editable__.ts_offline-*.pth'))
    if len(pth) != 1:
        raise RuntimeError('无法确定项目源码的 Python 路径配置。')
    destination = destination.absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f'输出文件已存在，未覆盖：{destination}')
    fd, temporary_name = tempfile.mkstemp(prefix='.ts-offline-', suffix='.tar.gz', dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(temporary, 'w:gz', compresslevel=1) as archive:
            for path in paths:
                archive.add(path, arcname='ts/' + str(path.relative_to(ROOT)), filter=archive_filter)
            add_bytes(archive, '.venv-uv/pyvenv.cfg', cfg.encode('utf-8'))
            add_bytes(archive, str(pth[0].relative_to(ROOT)), b'../../../../src\n')
            for name, path in sorted(libraries.items()):
                archive.add(path, arcname='ts/.runtime/vendor/lib/' + name, filter=archive_filter)
            for package, path in licenses.items():
                archive.add(path, arcname='ts/.runtime/vendor/licenses/' + package + '.copyright', filter=archive_filter)
            inventory = ''.join(f'{name}\t{path}\n' for name, path in sorted(libraries.items()))
            add_bytes(archive, '.runtime/vendor/native-libraries.tsv', inventory.encode('utf-8'))
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'离线包：{destination}')
    print(f'SHA256：{checksum(destination)}')


def main():
    parser = argparse.ArgumentParser(description='制作包含两个模型的 Linux 离线包')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/ts-offline-linux-x86_64.tar.gz')
    args = parser.parse_args()
    try:
        build(args.output)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f'离线包制作失败：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
