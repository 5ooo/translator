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
    raise RuntimeError('模型下载失败，请将已校验模型放入 ' + str(cache) + '\n' + '\n'.join(errors))


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


def install_command():
    destination = Path.home() / '.local/bin/ts'
    source = ROOT / 'bin/ts'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() and destination.resolve() == source:
        return
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f'{destination} 已存在且属于其他命令，未覆盖。可直接运行 {source}')
    destination.symlink_to(source)
    if str(destination.parent) not in os.environ['PATH'].split(os.pathsep):
        print(f'请将 {destination.parent} 加入 PATH；当前可使用 {source}', flush=True)


def main():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    environment()
    install_native()
    install_models()
    install_command()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'环境安装失败：{exc}', file=sys.stderr)
        raise SystemExit(1)
