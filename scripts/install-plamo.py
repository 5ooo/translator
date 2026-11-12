#!/usr/bin/env python3
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = 'plamo-3-translate-0.8b-Q4_K_M.gguf'
MODEL_REVISION = '1cf96ae02133958a20074bfdfab76517bb737d00'
MODEL_URL = f'https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF/resolve/{MODEL_REVISION}/{MODEL_NAME}'
MODEL_SHA256 = '70891ec70dc7ab4205745a38307867c2881b99239f20327927633abfe4bc9ec6'
RUNTIME_URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b12110/llama-b12110-bin-ubuntu-x64.tar.gz'
RUNTIME_SHA256 = '368227edcc229be5f9bed16a2223d79b5e41d0ac2e19bcf5825e82291c060e55'
VULKAN_URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b12110/llama-b12110-bin-ubuntu-vulkan-x64.tar.gz'
VULKAN_SHA256 = 'a5d741940956ec62e8783aee7e5a4c7c761af867d6f027c3277a51e1a3ac59b0'
RUNTIME_DIRECTORY = 'llama-b12110-cpu'


def model_destination():
    explicit = os.environ.get('TS_PLAMO_MODEL')
    if explicit is not None:
        if not explicit.strip():
            raise RuntimeError('TS_PLAMO_MODEL 为空，请指定本地模型文件。')
        return Path(explicit).expanduser()
    if data_home := os.environ.get('XDG_DATA_HOME'):
        return Path(data_home).expanduser() / 'ts/models/plamo3' / MODEL_NAME
    return ROOT / '.runtime/data/ts/models/plamo3' / MODEL_NAME


def runtime_destination(variant='cpu'):
    name = RUNTIME_DIRECTORY if variant == 'cpu' else 'llama-b12110-vulkan'
    return ROOT / '.runtime/tools' / name


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def _fetch(source, url, target, expected):
    if source is not None:
        source = source.expanduser()
        if not source.is_file():
            raise RuntimeError(f'本地文件不存在：{source}')
        print(f'复制 {source.name}', flush=True)
        with source.open('rb') as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
    else:
        print(f'下载 {url}', flush=True)
        with urllib.request.urlopen(url, timeout=90) as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
    if digest(target) != expected:
        raise RuntimeError(f'{target.name} 的 SHA256 校验失败，未安装。')


def _publish_directory(source, target):
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise RuntimeError('当前系统不支持安全原子安装，未覆盖已有文件。') from exc
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(code, os.strerror(code), str(target))
        raise OSError(code, os.strerror(code), str(target))


def _matches_model(path):
    try:
        return path.is_file() and digest(path) == MODEL_SHA256
    except OSError:
        return False


def _matches_runtime(directory, expected_archive):
    try:
        manifest = json.loads((directory / 'install-manifest.json').read_text(encoding='utf-8'))
        if manifest.get('archive_sha256') != expected_archive:
            return False
        files = manifest['files']
        if not isinstance(files, dict) or 'llama-server' not in files:
            return False
        for name, expected in files.items():
            if Path(name).name != name or not isinstance(expected, dict):
                return False
            path = directory / name
            if 'link' in expected:
                if not path.is_symlink() or os.readlink(path) != expected['link']:
                    return False
            elif path.is_symlink() or not path.is_file() or digest(path) != expected.get('sha256'):
                return False
        return os.access(directory / 'llama-server', os.X_OK)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _extract_runtime(archive_path, target, expected_archive):
    files = {}
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.parts == ('llama-b12110',) and member.isdir():
                continue
            if len(name.parts) != 2 or name.parts[0] != 'llama-b12110':
                raise RuntimeError('运行器压缩包包含不支持的路径。')
            filename = name.parts[1]
            if filename not in ('llama-server', 'LICENSE') and not filename.startswith('lib'):
                continue
            path = target / filename
            if member.isfile():
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError('无法读取运行器文件。')
                with source, path.open('xb') as writer:
                    shutil.copyfileobj(source, writer, length=1024 * 1024)
                path.chmod(member.mode & 0o777)
                files[filename] = {'sha256': digest(path)}
            elif member.issym():
                if Path(member.linkname).name != member.linkname or member.linkname in ('', '.', '..'):
                    raise RuntimeError('运行器压缩包包含不安全的链接。')
                path.symlink_to(member.linkname)
                files[filename] = {'link': member.linkname}
            else:
                raise RuntimeError('运行器压缩包包含不支持的文件类型。')
    if 'llama-server' not in files:
        raise RuntimeError('运行器压缩包缺少 llama-server。')
    manifest = {'archive_sha256': expected_archive, 'files': files}
    (target / 'install-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if not _matches_runtime(target, expected_archive):
        raise RuntimeError('运行器文件校验失败。')


def install_model(source=None):
    target = model_destination()
    if os.path.lexists(target):
        if _matches_model(target):
            print(f'PLaMo 模型已安装：{target}', flush=True)
            return target
        raise RuntimeError(f'{target} 已存在且不是指定模型，未覆盖。')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{target.name}-install-', dir=target.parent) as temporary:
        staged = Path(temporary) / MODEL_NAME
        _fetch(source, MODEL_URL, staged, MODEL_SHA256)
        try:
            os.link(staged, target)
        except FileExistsError as exc:
            if _matches_model(target):
                return target
            raise RuntimeError(f'{target} 在安装期间出现，未覆盖。') from exc
    print(f'PLaMo 模型已安装：{target}', flush=True)
    return target


def install_runtime(source=None, variant='cpu'):
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('自动安装运行器目前只支持 Linux x86-64；可用 --model-only 并自行提供 llama-server。')
    target = runtime_destination(variant)
    url, expected = (RUNTIME_URL, RUNTIME_SHA256) if variant == 'cpu' else (VULKAN_URL, VULKAN_SHA256)
    if os.path.lexists(target):
        if _matches_runtime(target, expected):
            print(f'PLaMo {variant} 运行器已安装：{target}', flush=True)
            return target
        raise RuntimeError(f'{target} 已存在且不是完整的指定版本，未覆盖。')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{target.name}-install-', dir=target.parent) as temporary:
        temporary = Path(temporary)
        archive = temporary / 'llama-runtime.tar.gz'
        staged = temporary / 'runtime'
        staged.mkdir()
        _fetch(source, url, archive, expected)
        _extract_runtime(archive, staged, expected)
        try:
            _publish_directory(staged, target)
        except FileExistsError as exc:
            if _matches_runtime(target, expected):
                return target
            raise RuntimeError(f'{target} 在安装期间出现，未覆盖。') from exc
    print(f'PLaMo {variant} 运行器已安装：{target}', flush=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='安装固定版本的 PLaMo 3 离线翻译模型')
    parser.add_argument('--model-file', type=Path, help='从本地 GGUF 文件安装，不下载模型')
    parser.add_argument('--runtime-archive', type=Path, help='从本地官方压缩包安装，不下载运行器')
    parser.add_argument('--vulkan', action='store_true', help='额外安装官方 Vulkan 显卡运行器')
    parser.add_argument('--vulkan-archive', type=Path, help='从本地官方 Vulkan 压缩包安装')
    parser.add_argument('--model-only', action='store_true', help='只安装模型，使用已有 llama-server')
    args = parser.parse_args(argv)
    if args.model_only and (args.runtime_archive or args.vulkan or args.vulkan_archive):
        parser.error('--model-only 不可与运行器安装选项同时使用')
    try:
        install_model(args.model_file)
        if not args.model_only:
            install_runtime(args.runtime_archive)
        if args.vulkan or args.vulkan_archive:
            install_runtime(args.vulkan_archive, 'vulkan')
        return 0
    except (OSError, RuntimeError, ValueError, tarfile.TarError) as exc:
        print(f'PLaMo 安装失败：{exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('PLaMo 安装已取消。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
