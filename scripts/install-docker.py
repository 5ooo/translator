#!/usr/bin/env python3
"""Install or disable the optional, project-owned Docker OCR and translation service."""
import argparse
import csv
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from provision import environment
from ts import ocr, plamo
from ts.errors import TsError
from ts.models import MODELS, default_model
from ts.resident import PROTOCOL, ROOT, host_bindings, request, service_config_path, source_digest

LABEL = 'io.translator.ts.instance'
CONTAINER_ID = re.compile(r'^[a-f0-9]{12,64}$')
INSTANCE = re.compile(r'^[a-f0-9]{32}$')


def docker(*args, capture=False, check=True, timeout=180):
    try:
        return subprocess.run(['docker', *map(str, args)], check=check, text=True,
                              capture_output=capture, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError('未找到 Docker，请先安装 Docker 并启动服务。') from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Docker 操作超时，请检查 Docker 服务。') from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or '').strip()
        raise RuntimeError(f'Docker 操作失败{f"：{detail}" if detail else ""}') from exc


def mount(source, target, readonly=True):
    row = ['type=bind', f'source={Path(source).resolve()}', f'target={target}']
    if readonly:
        row.append('readonly')
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator='').writerow(row)
    return buffer.getvalue()


def host_paths():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Docker 常驻模式需要项目 Python 3.12 环境，请重新运行标准安装。')
    site = ROOT / '.venv-uv/lib/python3.12/site-packages'
    packages = Path(os.environ['ARGOS_PACKAGES_DIR']).expanduser()
    model = plamo._model_file()
    ocr_models = ocr.model_files('tiny')[0].parent
    tools = ROOT / '.runtime/tools'
    for path in (site, packages, model, ocr_models, tools):
        if not path.exists():
            raise RuntimeError(f'缺少 Docker 常驻服务所需文件：{path}')
    custom = os.environ.get('TS_PLAMO_RUNNER')
    if custom is not None:
        candidates = plamo._runner_candidates()
        runner = candidates[0][0].resolve()
    else:
        runner = None
    return {'site': site.resolve(), 'packages': packages.resolve(), 'model': model.resolve(),
            'ocr': ocr_models.resolve(), 'tools': tools.resolve(), 'runner': runner}


def build_image(instance):
    tag = f'ts-resident-{os.getuid()}:{instance}'
    # A random tag and label avoid touching existing images.
    if docker('image', 'inspect', tag, capture=True, check=False).returncode == 0:
        raise RuntimeError('随机镜像名称已存在，未覆盖。请重试。')
    with tempfile.TemporaryDirectory(prefix='ts-docker-context-') as directory:
        context = Path(directory)
        shutil.copy2(ROOT / 'docker/Dockerfile', context / 'Dockerfile')
        (context / 'src').mkdir()
        shutil.copytree(ROOT / 'src/ts', context / 'src/ts',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        docker('build', '--label', f'{LABEL}={instance}', '-t', tag, str(context), timeout=1800)
    return tag


def rootless():
    result = docker('info', '--format', '{{json .SecurityOptions}}', capture=True)
    try:
        options = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError('无法读取 Docker 用户命名空间信息。') from exc
    return any(str(item).startswith('name=rootless') for item in options)


def can_try_nvidia(paths):
    if os.environ.get('TS_PLAMO_DEVICE', 'auto').strip().lower() == 'cpu':
        return False
    if not (paths['tools'] / 'llama-b12110-vulkan/llama-server').is_file() and paths['runner'] is None:
        return False
    tool = shutil.which('nvidia-smi')
    if not tool:
        return False
    try:
        result = subprocess.run([tool, '--query-gpu=name', '--format=csv,noheader'],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def create_container(config, paths, *, gpu, is_rootless):
    instance, tag = config['instance'], config['image_tag']
    name = f'ts-resident-{os.getuid()}-{instance[:12]}'
    config['container_name'] = name
    private = ROOT / '.runtime/docker' / instance
    private.mkdir(mode=0o700)
    config['directory_owned'] = True
    os.chmod(private, 0o700)
    user = '0:0' if is_rootless else f'{os.getuid()}:{os.getgid()}'
    args = ['run', '-d', '--name', name, '--label', f'{LABEL}={instance}',
            '--restart', 'unless-stopped', '--init', '--network', 'none', '--read-only',
            '--tmpfs', '/tmp:rw,nosuid,nodev,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--user', user,
            '--mount', mount(private, '/run/ts', False),
            '--mount', mount(paths['site'], '/deps'),
            '--mount', mount(paths['packages'], '/models/argos'),
            '--mount', mount(paths['model'], '/models/plamo.gguf'),
            '--mount', mount(paths['ocr'], '/app/.runtime/data/ts/models/ocr'),
            '--mount', mount(paths['tools'], '/app/.runtime/tools'),
            '-e', 'ARGOS_PACKAGES_DIR=/models/argos',
            '-e', 'TS_PLAMO_MODEL=/models/plamo.gguf',
            '-e', f'TS_PLAMO_DEVICE={"auto" if gpu else "cpu"}']
    if paths['runner']:
        args += ['--mount', mount(paths['runner'].parent, '/custom-runner'),
                 '-e', f'TS_PLAMO_RUNNER=/custom-runner/{paths["runner"].name}']
    if gpu:
        args += ['--gpus', 'all', '-e', 'NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics']
    args += [tag, '--socket', '/run/ts/service.sock', '--instance', instance,
             '--model', config['warm_model']]
    result = docker(*args, capture=True, timeout=90)
    container = result.stdout.strip()
    if not CONTAINER_ID.fullmatch(container):
        raise RuntimeError('Docker 未返回有效的容器标识。')
    config['container_id'] = container
    config['device'] = 'nvidia' if gpu else 'cpu'


def remove_container(config):
    instance = config.get('instance')
    if not isinstance(instance, str) or not INSTANCE.fullmatch(instance):
        return
    identifier = config.get('container_id')
    if identifier is not None:
        if not isinstance(identifier, str) or not CONTAINER_ID.fullmatch(identifier):
            raise RuntimeError('原容器标识无效，未清理。')
        filter_value = f'id={identifier}'
    elif config.get('container_name') == f'ts-resident-{os.getuid()}-{instance[:12]}':
        filter_value = f'name=^/{config["container_name"]}$'
    else:
        filter_value = None
    if filter_value:
        result = docker('ps', '-aq', '--no-trunc', '--filter', filter_value, capture=True)
        matches = result.stdout.split()
        if len(matches) > 1 or any(not CONTAINER_ID.fullmatch(item) for item in matches):
            raise RuntimeError('无法确定原容器的身份，未清理。')
        if matches:
            found = matches[0]
            label = docker('inspect', '--format', f'{{{{index .Config.Labels "{LABEL}"}}}}',
                           found, capture=True).stdout.strip()
            if label != instance:
                raise RuntimeError('原容器不属于本项目，未清理。')
            docker('rm', '-f', found, capture=True)
    if config.get('directory_owned') is True:
        directory = ROOT / '.runtime/docker' / instance
        try:
            sock = directory / 'service.sock'
            if sock.is_socket() and sock.stat().st_uid == os.getuid():
                sock.unlink()
            directory.rmdir()
        except (FileNotFoundError, OSError):
            pass


def remove_image(config):
    tag, instance = config.get('image_tag'), config.get('instance')
    if not isinstance(instance, str) or not INSTANCE.fullmatch(instance):
        return
    if tag != f'ts-resident-{os.getuid()}:{instance}':
        return
    result = docker('image', 'ls', '-q', '--no-trunc', '--filter', f'reference={tag}', capture=True)
    if not result.stdout.strip():
        return
    label = docker('image', 'inspect', '--format', f'{{{{index .Config.Labels "{LABEL}"}}}}',
                   tag, capture=True).stdout.strip()
    if label != instance:
        raise RuntimeError('原镜像不属于本项目，未清理。')
    docker('image', 'rm', tag, capture=True)


def wait_ready(config):
    deadline = time.monotonic() + 120
    last = None
    while time.monotonic() < deadline:
        try:
            status = request(config, 'ping', timeout=3)
            result = request(config, 'translate', model=config['warm_model'],
                             text='The network is ready.', timeout=120)
            variant = MODELS[config['warm_model']].ocr_variant
            if (variant in status.get('ocr_loaded', []) and isinstance(result.get('text'), str)
                    and result['text'].strip()):
                return
        except TsError as exc:
            last = exc
        container = config.get('container_id')
        if container:
            state = docker('inspect', '--format', '{{.State.Running}}', container,
                           capture=True, check=False)
            if state.returncode != 0 or state.stdout.strip() != 'true':
                logs = docker('logs', '--tail', '10', container, capture=True, check=False)
                raise RuntimeError(f'常驻容器启动失败：{(logs.stderr or logs.stdout).strip()}')
        time.sleep(.25)
    raise RuntimeError(f'等待 Docker 常驻服务预热超时：{last}')


def confirm_nvidia(config):
    result = request(config, 'translate', model='plamo', text='The network is ready.', timeout=120)
    if not isinstance(result.get('text'), str) or not result['text'].strip():
        raise RuntimeError('无法完成显卡模式的翻译测试。')
    processes = docker('top', config['container_id'], '-eo', 'pid,comm', capture=True)
    pids = {line.split()[0] for line in processes.stdout.splitlines()[1:]
            if line.split() and line.split()[0].isdigit()}
    try:
        gpu = subprocess.run(['nvidia-smi', '--query-compute-apps=pid,used_memory',
                              '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('无法验证容器显卡使用情况。') from exc
    for line in gpu.stdout.splitlines():
        parts = [part.strip() for part in line.split(',')]
        if len(parts) >= 2 and parts[0] in pids and parts[1].isdigit() and int(parts[1]) > 0:
            return
    raise RuntimeError('未检测到容器中的模型进程使用 NVIDIA 显存。')


def write_config(config, expected):
    path = service_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.resident-', delete=False) as file:
            temp = Path(file.name)
            json.dump(config, file, ensure_ascii=False, indent=2)
            file.write('\n')
        os.chmod(temp, 0o600)
        if expected is None:
            try:
                os.link(temp, path)
            except FileExistsError as exc:
                raise RuntimeError('常驻服务配置在安装期间出现，未覆盖。') from exc
        else:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise RuntimeError('常驻服务配置在安装期间发生变化，未覆盖。')
            os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def existing_config():
    path = service_config_path()
    if path.is_symlink():
        raise RuntimeError('现有常驻服务配置是符号链接，未覆盖。')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'现有常驻服务配置无法读取，未覆盖：{exc}') from exc
    if not isinstance(data, dict) or not INSTANCE.fullmatch(str(data.get('instance', ''))):
        raise RuntimeError('现有常驻服务配置不属于本项目，未覆盖。')
    instance = data['instance']
    if (data.get('protocol') not in (1, PROTOCOL) or data.get('directory_owned') is not True
            or not CONTAINER_ID.fullmatch(str(data.get('container_id', '')))
            or data.get('container_name') != f'ts-resident-{os.getuid()}-{instance[:12]}'
            or data.get('image_tag') != f'ts-resident-{os.getuid()}:{instance}'
            or not re.fullmatch(r'[a-f0-9]{64}', str(data.get('source_digest', '')))
            or not isinstance(data.get('host_bindings'), dict)):
        raise RuntimeError('现有常驻服务配置不属于本项目，未覆盖。')
    old_root = data.get('root')
    if not isinstance(old_root, str) or (old_root != str(ROOT) and Path(old_root).exists()):
        raise RuntimeError('现有常驻服务配置属于另一个项目，未覆盖。')
    return data


def install():
    docker('info', '--format', '{{.ServerVersion}}', capture=True)
    paths = host_paths()
    selected = default_model()
    old = existing_config()
    old_contents = service_config_path().read_bytes() if old is not None else None
    instance = uuid.uuid4().hex
    config = {'protocol': PROTOCOL, 'root': str(ROOT), 'instance': instance,
              'source_digest': source_digest(), 'warm_model': selected,
              'host_bindings': host_bindings()}
    gpu_fallback = False
    try:
        config['image_tag'] = build_image(instance)
        is_rootless = rootless()
        if can_try_nvidia(paths):
            try:
                create_container(config, paths, gpu=True, is_rootless=is_rootless)
                wait_ready(config)
                confirm_nvidia(config)
            except (RuntimeError, TsError) as exc:
                gpu_fallback = True
                if os.environ.get('TS_DOCKER_DEBUG') == '1':
                    print(f'显卡启动详情：{exc}', file=sys.stderr, flush=True)
                remove_container(config)
                config.pop('container_id', None)
                config.pop('container_name', None)
                create_container(config, paths, gpu=False, is_rootless=is_rootless)
                wait_ready(config)
        else:
            create_container(config, paths, gpu=False, is_rootless=is_rootless)
            wait_ready(config)
        write_config(config, old_contents)
    except BaseException:
        try:
            remove_container(config)
            remove_image(config)
        except RuntimeError as exc:
            print(f'未能清理本次创建的 Docker 资源：{exc}', file=sys.stderr)
        raise
    if old and old['instance'] != instance:
        try:
            remove_container(old)
            remove_image(old)
        except RuntimeError as exc:
            print(f'新服务已启用，但未能清理旧服务 {old.get("container_name")} '
                  f'（{old.get("container_id")}）、镜像 {old.get("image_tag")}：{exc}', file=sys.stderr)
    device = 'NVIDIA GPU' if config['device'] == 'nvidia' else 'CPU'
    note = '（显卡加速未启用）' if gpu_fallback else ''
    print(f'Docker 常驻服务：{device}{note}', flush=True)


def disable():
    path = service_config_path()
    try:
        before = path.read_bytes()
    except FileNotFoundError:
        before = None
    old = existing_config()
    if old is None:
        print('当前已使用本地模式。')
        return
    docker('info', '--format', '{{.ServerVersion}}', capture=True)
    remove_container(old)
    remove_image(old)
    if before is None or path.is_symlink() or path.read_bytes() != before:
        raise RuntimeError('常驻服务配置在切换期间发生变化，未删除。')
    path.unlink()
    print('已切回本地模式。')


def main():
    parser = argparse.ArgumentParser(description='配置 ts Docker 常驻服务')
    parser.add_argument('action', choices=['install', 'disable'])
    args = parser.parse_args()
    environment()
    lock_dir = ROOT / '.runtime/docker'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / 'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == 'install':
            install()
        else:
            disable()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, TsError) as exc:
        print(f'Docker 常驻服务配置失败：{exc}', file=sys.stderr)
        raise SystemExit(1)
