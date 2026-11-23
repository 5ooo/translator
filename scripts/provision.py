import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
SYSTEM = RUNTIME / 'system'
PACKAGES = RUNTIME / 'data/argos-translate/packages'
SYSTEM_BIN = Path('/usr/local/bin')
NATIVE_PACKAGES = ('tesseract-ocr', 'tesseract-ocr-eng', 'tesseract-ocr-chi-sim',
                   'tesseract-ocr-osd', 'wl-clipboard', 'xclip')


def environment():
    os.environ['PATH'] = str(SYSTEM / 'usr/bin') + os.pathsep + os.environ['PATH']
    os.environ['LD_LIBRARY_PATH'] = str(SYSTEM / 'usr/lib/x86_64-linux-gnu') + os.pathsep + os.environ.get('LD_LIBRARY_PATH', '')
    for key, directory in [('XDG_DATA_HOME', 'data'), ('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache')]:
        os.environ.setdefault(key, str(RUNTIME / directory))
    os.environ.setdefault('ARGOS_PACKAGES_DIR', str(PACKAGES))
    if (SYSTEM / 'usr/share/tesseract-ocr/5/tessdata').is_dir():
        os.environ.setdefault('TESSDATA_PREFIX', str(SYSTEM / 'usr/share/tesseract-ocr/5/tessdata'))


def native_ready():
    if not all(shutil.which(tool) for tool in ('tesseract', 'wl-paste', 'xclip')):
        return False
    result = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True)
    return result.returncode == 0 and {'eng', 'chi_sim'}.issubset(result.stdout.split())


def install_native():
    if native_ready():
        return
    if not shutil.which('apt-get') or not shutil.which('dpkg-deb'):
        raise RuntimeError('当前自动部署支持 Debian/Ubuntu。请先安装 Tesseract eng+chi_sim、wl-clipboard 与 xclip。')
    SYSTEM.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ts-packages-') as directory:
        subprocess.run(['apt-get', 'download', *NATIVE_PACKAGES], cwd=directory, check=True)
        records = []
        for archive in sorted(Path(directory).glob('*.deb')):
            subprocess.run(['dpkg-deb', '-x', str(archive), str(SYSTEM)], check=True)
            records.append({'file': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})
        (RUNTIME / 'native-packages.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    environment()
    if not native_ready():
        raise RuntimeError('本地系统工具仍不可用。请检查缺少的系统共享库和 Tesseract 语言包。')


def verified_download(spec):
    cache = RUNTIME / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / spec['filename']
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == spec['sha256']:
        return path
    errors = []
    partial = path.with_suffix('.part')
    for url in spec['urls']:
        try:
            print(f'下载 {spec["from"]}→{spec["to"]} 本地模型：{url}', flush=True)
            with urllib.request.urlopen(url, timeout=60) as source, partial.open('wb') as output:
                shutil.copyfileobj(source, output)
            if hashlib.sha256(partial.read_bytes()).hexdigest() != spec['sha256']:
                raise ValueError('模型 SHA256 校验失败')
            partial.replace(path)
            return path
        except Exception as exc:
            errors.append(f'{url}: {exc}')
            partial.unlink(missing_ok=True)
    raise RuntimeError('模型下载失败，请检查网络后重新运行 ./install.sh。\n' + '\n'.join(errors))


def install_models():
    from argostranslate import package
    specs = json.loads((ROOT / 'scripts/models.json').read_text(encoding='utf-8'))
    installed = {(p.from_code, p.to_code, p.package_version) for p in package.get_installed_packages()
                 if p.type == 'translate' and hasattr(p, 'tokenizer') and (p.package_path / 'model').is_dir()}
    for spec in specs:
        if (spec['from'], spec['to'], spec['version']) in installed:
            continue
        archive = verified_download(spec)
        package.install_from_path(archive)
        print(f'已安装本地模型 {spec["from"]}→{spec["to"]}', flush=True)


def install_command(command_path=None):
    search_path = os.environ.get('PATH', '') if command_path is None else command_path
    source = ROOT / 'bin/ts'
    existing = shutil.which('ts', path=search_path)
    if existing:
        if Path(existing).resolve() == source.resolve():
            return
        raise RuntimeError(f'{existing} 已存在且属于其他命令，未覆盖。可直接运行 {source}')

    entries = [Path(value) for value in search_path.split(os.pathsep)
               if value and Path(value).is_absolute()]
    entry_paths = {entry.resolve() for entry in entries}
    user_bins = [Path.home() / '.local/bin', Path.home() / 'bin']

    def link(destination):
        if destination.is_symlink() and destination.resolve() == source.resolve():
            return
        if destination.exists() or destination.is_symlink():
            raise RuntimeError(f'{destination} 已存在且属于其他命令，未覆盖。可直接运行 {source}')
        try:
            destination.symlink_to(source)
        except FileExistsError as exc:
            raise RuntimeError(f'{destination} 在安装期间出现，未覆盖。') from exc

    for directory in user_bins:
        if directory.resolve() not in entry_paths:
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
            link(directory / 'ts')
            return
        except PermissionError:
            continue

    if SYSTEM_BIN.resolve() not in entry_paths or not SYSTEM_BIN.is_dir():
        raise RuntimeError(f'PATH 中没有可用的命令目录。可直接运行 {source}')
    destination = SYSTEM_BIN / 'ts'
    try:
        link(destination)
    except PermissionError as exc:
        sudo = shutil.which('sudo', path=search_path)
        if not sudo:
            raise RuntimeError(f'安装到 {SYSTEM_BIN} 需要管理员权限。可直接运行 {source}') from exc
        print(f'需要管理员权限以安装 {destination}。', flush=True)
        try:
            subprocess.run([sudo, '/usr/bin/ln', '-sT', '--', str(source), str(destination)], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f'无法安装 {destination}，未覆盖已有文件。可直接运行 {source}') from error
        if not destination.is_symlink() or destination.resolve() != source.resolve():
            raise RuntimeError(f'无法确认 {destination} 指向项目命令。')


def main():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    command_path = os.environ.get('PATH', '')
    environment()
    install_native()
    install_models()
    install_command(command_path)


if __name__ == '__main__':
    try:
        argparse.ArgumentParser(description='准备 ts 运行环境').parse_args()
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'环境安装失败：{exc}', file=sys.stderr)
        raise SystemExit(1)
