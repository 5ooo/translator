"""Private, offline translation service used by the optional Docker mode."""
import argparse
from contextlib import ExitStack, contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import time

from .engine import Detector
from .errors import TsError
from .models import MODELS, config_path, open_translator
from .text import translate_text

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = 1
MAX_MESSAGE = 16 * 1024 * 1024
INSTANCE = re.compile(r'^[a-f0-9]{32}$')
CONTAINER_ID = re.compile(r'^[a-f0-9]{12,64}$')


class ServiceUnavailable(TsError):
    pass


def source_digest(directory=None):
    directory = Path(directory or Path(__file__).resolve().parent)
    digest = hashlib.sha256()
    for path in sorted(directory.glob('*.py')):
        digest.update(path.name.encode('utf-8') + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def service_config_path():
    return config_path().with_name('resident.json')


def host_bindings():
    from .plamo import _model_file
    packages = os.environ.get('ARGOS_PACKAGES_DIR', str(ROOT / '.runtime/data/argos-translate/packages'))
    runner = os.environ.get('TS_PLAMO_RUNNER')
    return {
        'packages': str(Path(packages).expanduser().resolve()),
        'model': str(_model_file().resolve()),
        'runner': str(Path(runner).expanduser().resolve()) if runner else None,
        'device': os.environ.get('TS_PLAMO_DEVICE', 'auto').strip().lower(),
    }


def read_service_config():
    if os.environ.get('TS_INSTALL_CHECK') == '1':
        return None
    path = service_config_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TsError(f'无法读取 Docker 常驻服务配置：{exc}') from exc
    if not isinstance(data, dict) or data.get('protocol') != PROTOCOL:
        raise TsError('Docker 常驻服务配置不兼容；请运行 ./install.sh --docker 重新安装。')
    if not isinstance(data.get('instance'), str) or not INSTANCE.fullmatch(data['instance']):
        raise TsError('Docker 常驻服务配置无效；请运行 ./install.sh --docker 重新安装。')
    if data.get('root') != str(ROOT):
        raise TsError('项目位置已改变；请运行 ./install.sh --docker 重建常驻服务。')
    if data.get('source_digest') != source_digest():
        raise TsError('项目代码已更新；请运行 ./install.sh --docker 更新常驻服务。')
    if data.get('host_bindings') != host_bindings():
        raise TsError('模型或运行器配置已改变；请运行 ./install.sh --docker 更新常驻服务。')
    return data


def socket_path(config):
    return ROOT / '.runtime' / 'docker' / config['instance'] / 'service.sock'


def _validate_socket_directory(path):
    try:
        info = path.parent.lstat()
    except OSError as exc:
        raise TsError('Docker 常驻服务目录不存在；请运行 ./install.sh --docker 修复。') from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise TsError('Docker 常驻服务目录权限不安全，请检查目录所有者和权限。')


@contextmanager
def _socket_address(path):
    try:
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TsError('Docker 常驻服务目录不可用，请检查目录权限。') from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TsError('Docker 常驻服务目录权限不安全，请检查目录所有者和权限。')
        yield f'/proc/self/fd/{fd}/{path.name}'
    finally:
        os.close(fd)


def _peer_uid(conn):
    try:
        raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
        return struct.unpack('3i', raw)[1]
    except (OSError, AttributeError, struct.error) as exc:
        raise TsError('无法验证 Docker 常驻服务的本地用户身份。') from exc


def _send(conn, value):
    data = (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    if len(data) > MAX_MESSAGE:
        raise TsError('输入或译文过长，超出 Docker 常驻服务的消息大小限制。')
    conn.sendall(data)


def _receive(conn):
    data = bytearray()
    while not data.endswith(b'\n'):
        chunk = conn.recv(min(65536, MAX_MESSAGE + 1 - len(data)))
        if not chunk:
            raise TsError('Docker 常驻服务提前关闭连接。')
        data.extend(chunk)
        if len(data) > MAX_MESSAGE:
            raise TsError('Docker 常驻服务消息过长。')
    try:
        value = json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise TsError('Docker 常驻服务返回了无效消息。') from exc
    if not isinstance(value, dict):
        raise TsError('Docker 常驻服务返回了无效消息。')
    return value


def _request_once(config, operation, *, model=None, text=None, timeout=None):
    path = socket_path(config)
    _validate_socket_directory(path)
    payload = {'protocol': PROTOCOL, 'instance': config['instance'],
               'source_digest': config['source_digest'], 'operation': operation}
    if operation == 'translate':
        payload.update(model=model, text=text)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(3.0)
            try:
                with _socket_address(path) as address:
                    conn.connect(address)
            except (OSError, TimeoutError) as exc:
                raise ServiceUnavailable('Docker 常驻服务不可用；请运行 ./install.sh --docker 修复，或 ./install.sh --local 切回本地模式。') from exc
            if _peer_uid(conn) != os.getuid():
                raise TsError('Docker 常驻服务的用户身份不符，已拒绝连接。')
            conn.settimeout(timeout)
            _send(conn, payload)
            answer = _receive(conn)
    except (OSError, TimeoutError) as exc:
        raise TsError('Docker 常驻服务连接中断，请检查服务后重试。') from exc
    if answer.get('protocol') != PROTOCOL or answer.get('instance') != config['instance']:
        raise TsError('Docker 常驻服务版本或身份不符；请运行 ./install.sh --docker 更新。')
    if answer.get('ok') is not True:
        message = answer.get('error')
        raise TsError(message if isinstance(message, str) and message else 'Docker 常驻服务处理失败。')
    return answer


def _container_running(config):
    identifier, instance = config.get('container_id'), config['instance']
    if not isinstance(identifier, str) or not CONTAINER_ID.fullmatch(identifier):
        return False
    try:
        result = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.Running}} {{index .Config.Labels "io.translator.ts.instance"}}', identifier],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == f'true {instance}'


def request(config, operation, *, model=None, text=None, timeout=None, wait_if_starting=False):
    try:
        return _request_once(config, operation, model=model, text=text, timeout=timeout)
    except ServiceUnavailable as exc:
        if not wait_if_starting or not _container_running(config):
            raise
        last = exc
    deadline = time.monotonic() + 60
    check_at = time.monotonic() + 2
    while time.monotonic() < deadline:
        time.sleep(.25)
        try:
            return _request_once(config, operation, model=model, text=text, timeout=timeout)
        except ServiceUnavailable as exc:
            last = exc
            if time.monotonic() >= check_at:
                if not _container_running(config):
                    raise last
                check_at = time.monotonic() + 2
    raise TsError('等待 Docker 常驻服务预热超时，请检查容器状态。')


class Runtime:
    def __init__(self):
        self.detector = Detector()
        self.engines = {}
        self.stack = ExitStack()

    def translate(self, text, model):
        if model not in MODELS:
            raise TsError('未知翻译模式。')
        if model not in self.engines:
            self.engines[model] = self.stack.enter_context(open_translator(model))
        return translate_text(text, self.detector, self.engines[model].translate)

    def warm(self, model):
        value = self.translate('The network is ready.', model)
        if not value.strip():
            raise TsError('Docker 常驻服务预热未得到译文。')

    def close(self):
        self.stack.close()


def _prepare_socket(path):
    _validate_socket_directory(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise TsError('服务 socket 位置已有其他文件，未覆盖。')
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(.5)
        with _socket_address(path) as address:
            probe.connect(address)
    except OSError as exc:
        if exc.errno not in (errno.ECONNREFUSED, errno.ENOENT):
            raise TsError('无法确认旧服务 socket 是否可用，未覆盖。') from exc
    else:
        raise TsError('已有服务正在使用该 socket，未覆盖。')
    finally:
        probe.close()
    path.unlink(missing_ok=True)


def serve(path, instance, model):
    path = Path(path)
    if not INSTANCE.fullmatch(instance) or model not in MODELS:
        raise TsError('Docker 常驻服务启动参数无效。')
    runtime = Runtime()
    listener = None
    created = False

    def terminate(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    try:
        runtime.warm(model)
        _prepare_socket(path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        with _socket_address(path) as address:
            listener.bind(address)
        created = True
        os.chmod(path, 0o600)
        listener.listen(16)
        while True:
            conn, _ = listener.accept()
            with conn:
                try:
                    conn.settimeout(5.0)
                    if _peer_uid(conn) != os.getuid():
                        raise TsError('请求用户身份不符。')
                    payload = _receive(conn)
                    if (payload.get('protocol') != PROTOCOL or payload.get('instance') != instance
                            or payload.get('source_digest') != source_digest()):
                        raise TsError('Docker 常驻服务版本或身份不符。')
                    operation = payload.get('operation')
                    if operation == 'ping':
                        value = {'ready': True, 'loaded': sorted(runtime.engines)}
                    elif operation == 'translate':
                        text, selected = payload.get('text'), payload.get('model')
                        if not isinstance(text, str) or not text.strip() or selected not in MODELS:
                            raise TsError('Docker 常驻服务收到无效翻译请求。')
                        value = {'text': runtime.translate(text, selected)}
                    else:
                        raise TsError('Docker 常驻服务收到未知请求。')
                    answer = {'protocol': PROTOCOL, 'instance': instance, 'ok': True, **value}
                except TsError as exc:
                    answer = {'protocol': PROTOCOL, 'instance': instance, 'ok': False, 'error': str(exc)}
                except Exception:
                    answer = {'protocol': PROTOCOL, 'instance': instance, 'ok': False, 'error': 'Docker 常驻服务处理失败。'}
                try:
                    _send(conn, answer)
                except (OSError, TsError):
                    pass
    finally:
        if listener is not None:
            listener.close()
        if created:
            path.unlink(missing_ok=True)
        runtime.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='ts Docker 常驻服务')
    parser.add_argument('--socket', required=True)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--model', choices=tuple(MODELS), required=True)
    args = parser.parse_args(argv)
    try:
        serve(args.socket, args.instance, args.model)
    except TsError as exc:
        print(f'ts 常驻服务：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
