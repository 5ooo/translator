import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time

from .errors import TsError
from .events import Stage, emit


_ROOT = Path(__file__).resolve().parents[2]
_MODEL_NAME = 'plamo-3-translate-0.8b-Q4_K_M.gguf'
_CONTEXT_SIZE = 4096
_MAX_PROMPT_BYTES = 2000
_MAX_PREDICT = 2048
_STARTUP_TIMEOUT = 45.0
_CONNECT_TIMEOUT = 3.0
_RESPONSE_TIMEOUT = 120.0
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_CONTROL_TOKEN = re.compile(r'<\|[^|\r\n]{1,80}\|>')


def _owned_tcp(pid):
    proc = Path('/proc') / str(pid)
    try:
        fds = list((proc / 'fd').iterdir())
    except FileNotFoundError:
        return []
    except PermissionError as exc:
        raise TsError('没有权限验证 PLaMo 运行器的本地连接。') from exc
    inodes = set()
    for fd in fds:
        try:
            link = os.readlink(fd)
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise TsError('没有权限验证 PLaMo 运行器的本地连接。') from exc
        match = re.fullmatch(r'socket:\[(\d+)\]', link)
        if match:
            inodes.add(match.group(1))
    try:
        rows = (proc / 'net/tcp').read_text().splitlines()[1:]
    except FileNotFoundError:
        if not proc.exists():
            return []
        raise TsError('无法读取 /proc 网络信息以验证 PLaMo 运行器。')
    except PermissionError as exc:
        raise TsError('没有权限读取 /proc 网络信息以验证 PLaMo 运行器。') from exc
    records = []
    for row in rows:
        fields = row.split()
        if len(fields) >= 10 and fields[9] in inodes:
            records.append((fields[1], fields[2], fields[3]))
    return records


def _loopback_port(address):
    if not address.startswith('0100007F:'):
        return None
    try:
        return int(address.split(':', 1)[1], 16)
    except ValueError:
        return None


def _model_file():
    explicit = os.environ.get('TS_PLAMO_MODEL')
    if explicit is not None:
        path = Path(explicit).expanduser() if explicit.strip() else None
        if path is None or not path.is_file() or not os.access(path, os.R_OK):
            raise TsError('TS_PLAMO_MODEL 指定的本地模型文件不存在或不可读。')
        return path
    paths = []
    if data_home := os.environ.get('XDG_DATA_HOME'):
        paths.append(Path(data_home).expanduser() / 'ts/models/plamo3' / _MODEL_NAME)
    bundled = _ROOT / '.runtime/data/ts/models/plamo3' / _MODEL_NAME
    if bundled not in paths:
        paths.append(bundled)
    for path in paths:
        if path.is_file() and os.access(path, os.R_OK):
            return path
    raise TsError('未找到 PLaMo 3 本地模型，请运行 python scripts/install-plamo.py 安装。')


def _runner_candidates():
    device = os.environ.get('TS_PLAMO_DEVICE', 'auto').strip().lower()
    if device not in ('auto', 'cpu'):
        raise TsError('TS_PLAMO_DEVICE 只能设置为 auto 或 cpu。')
    explicit = os.environ.get('TS_PLAMO_RUNNER')
    if explicit is not None:
        path = Path(explicit).expanduser() if explicit.strip() else None
        if path is None or not path.is_file() or not os.access(path, os.X_OK):
            raise TsError('TS_PLAMO_RUNNER 指定的运行器不存在或不可执行。')
        return [(path, '0')] if device == 'cpu' else [(path, '999'), (path, '0')]

    tools = _ROOT / '.runtime/tools'
    vulkan = tools / 'llama-b12110-vulkan/llama-server'
    cpu = tools / 'llama-b12110-cpu/llama-server'
    candidates = []
    if device == 'auto' and vulkan.is_file() and os.access(vulkan, os.X_OK):
        candidates.append((vulkan, '999'))
    if cpu.is_file() and os.access(cpu, os.X_OK):
        candidates.append((cpu, '0'))
    if not candidates and (system := shutil.which('llama-server')):
        path = Path(system)
        candidates = [(path, '0')] if device == 'cpu' else [(path, '999'), (path, '0')]
    if not candidates:
        raise TsError('未找到 PLaMo 运行器，请运行 python scripts/install-plamo.py 安装。')
    return candidates


def _resources():
    if not Path('/proc/self/fd').is_dir() or not os.access('/proc/self/net/tcp', os.R_OK):
        raise TsError('无法读取 Linux /proc 网络信息，不能安全验证 PLaMo 本地运行器。')
    return _model_file(), _runner_candidates()


def available():
    try:
        model, _ = _resources()
    except TsError as exc:
        return False, str(exc)
    return True, f'PLaMo 3 Q4_K_M 本地模型和运行器可用：{model}'


def _prompt(text, source, target):
    if (source, target) not in (('en', 'zh'), ('zh', 'en')):
        raise TsError('PLaMo 目前只支持中英文互译。')
    if _CONTROL_TOKEN.search(text):
        raise TsError('输入包含模型控制标记，请使用 Argos 模型翻译。')
    src = 'zh-hans' if source == 'zh' else 'en'
    dst = 'zh-hans' if target == 'zh' else 'en'
    prompt = ('<|plamo:tag|>dataset<|plamo:msg|>translation'
              f'<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>{src}'
              f'<|plamo:msg|>{text}'
              f'<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>{dst}<|plamo:msg|>')
    if len(prompt.encode('utf-8')) > _MAX_PROMPT_BYTES:
        raise TsError('待翻译片段过长，无法保证 PLaMo 完整处理；请分段后重试。')
    return prompt


def _parse_response(data):
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise TsError('PLaMo 返回了无法解析的结果。') from exc
    if not isinstance(result, dict):
        raise TsError('PLaMo 返回了无法解析的结果。')
    if result.get('error'):
        raise TsError('PLaMo 本地推理失败。')
    if result.get('truncated') or result.get('stop_type') not in ('eos', 'word'):
        raise TsError('PLaMo 译文不完整，请缩短输入后重试。')
    content = result.get('content')
    if not isinstance(content, str) or not content.strip():
        raise TsError('PLaMo 本地模型返回了空译文。')
    return content.strip()


class PlamoEngine:
    def __init__(self, *, on_stage=None):
        self.on_stage = on_stage
        self._process = None
        self._port = None
        self._log = None
        self._api_key = None

    def _alive(self):
        if self._process is None or self._process.poll() is not None:
            raise TsError('PLaMo 本地运行器已退出，请检查运行器和模型文件。')

    def _records(self):
        self._alive()
        try:
            return _owned_tcp(self._process.pid)
        except TsError as exc:
            raise TsError('无法验证 PLaMo 本地运行器的网络连接。') from exc

    def _verify_connection(self, client_port):
        deadline = time.monotonic() + _CONNECT_TIMEOUT
        while time.monotonic() < deadline:
            records = self._records()
            listening = any(state == '0A' and _loopback_port(local) == self._port
                            for local, _, state in records)
            connected = any(state == '01' and _loopback_port(local) == self._port
                            and _loopback_port(remote) == client_port
                            for local, remote, state in records)
            if listening and connected:
                return
            time.sleep(.01)
        raise TsError('无法验证 PLaMo 本地运行器的连接，已停止翻译。')

    def _request(self, method, path, payload=None, timeout=_CONNECT_TIMEOUT):
        self._alive()
        connection = http.client.HTTPConnection('127.0.0.1', self._port, timeout=timeout)
        try:
            connection.connect()
            self._verify_connection(connection.sock.getsockname()[1])
            body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers = {'Authorization': f'Bearer {self._api_key}'}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(data) > _MAX_RESPONSE_BYTES:
                raise TsError('PLaMo 返回的结果过长。')
            if response.status != 200 and not (path == '/health' and response.status == 503):
                raise TsError(f'PLaMo 本地运行器返回 HTTP {response.status}。')
            return data
        finally:
            connection.close()

    def _start_runner(self, executable, model, gpu_layers):
        self._log = tempfile.TemporaryFile(mode='w+b')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('LLAMA_ARG_') and key != 'LLAMA_API_KEY'}
        self._api_key = secrets.token_urlsafe(32)
        env['LLAMA_API_KEY'] = self._api_key
        if gpu_layers == '0':
            for variable in ('CUDA_VISIBLE_DEVICES', 'HIP_VISIBLE_DEVICES', 'ROCR_VISIBLE_DEVICES',
                             'GGML_VK_VISIBLE_DEVICES'):
                env[variable] = '-1'
        try:
            self._process = subprocess.Popen(
                [str(executable), '-m', str(model), '--host', '127.0.0.1', '--port', '0',
                 '-c', str(_CONTEXT_SIZE), '-t', '4', '--n-gpu-layers', gpu_layers,
                 '--parallel', '1', '--no-webui', '--cors-origins', 'localhost'],
                stdin=subprocess.DEVNULL, stdout=self._log, stderr=self._log, env=env,
            )
            deadline = time.monotonic() + _STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                ports = {port for local, _, state in self._records()
                         if state == '0A' and (port := _loopback_port(local)) is not None}
                if len(ports) > 1:
                    raise TsError('PLaMo 运行器监听了多个本地端口，无法安全选择。')
                if ports:
                    self._port = ports.pop()
                    break
                time.sleep(.05)
            else:
                raise TsError('等待 PLaMo 本地运行器启动超时。')
            while time.monotonic() < deadline:
                try:
                    state = json.loads(self._request('GET', '/health'))
                    if isinstance(state, dict) and state.get('status') == 'ok':
                        return
                except (ConnectionError, TimeoutError, http.client.HTTPException, ValueError):
                    pass
                time.sleep(.05)
            raise TsError('等待 PLaMo 模型加载超时。')
        except BaseException:
            self.close()
            raise

    def _start(self):
        if self._process is not None:
            self._alive()
            return
        model, candidates = _resources()
        emit(self.on_stage, Stage.MODEL)
        for executable, gpu_layers in candidates:
            try:
                self._start_runner(executable, model, gpu_layers)
                return
            except (TsError, OSError):
                continue
        raise TsError('PLaMo 本地运行器启动失败，请检查模型文件和运行器依赖。')

    def translate(self, text, source, target):
        try:
            prompt = _prompt(text, source, target)
            self._start()
            emit(self.on_stage, Stage.TRANSLATE)
            budget = min(_MAX_PREDICT, max(128, len(text.encode('utf-8')) * 4 + 128))
            payload = {'prompt': prompt, 'n_predict': budget, 'temperature': 0, 'top_k': 1,
                       'stream': False, 'stop': ['<|plamo:tag|>', '<|plamo:bos|>']}
            return _parse_response(self._request('POST', '/completion', payload, timeout=_RESPONSE_TIMEOUT))
        except TsError:
            self.close()
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            self.close()
            raise TsError(f'PLaMo 本地推理失败：{exc}') from exc
        except BaseException:
            self.close()
            raise

    def close(self):
        process, self._process = self._process, None
        self._port = None
        self._api_key = None
        try:
            if process is not None:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        process.wait()
                else:
                    process.wait()
        finally:
            if self._log is not None:
                self._log.close()
                self._log = None
