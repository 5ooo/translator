import importlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .errors import TsError


@dataclass(frozen=True)
class ModelSpec:
    title: str
    module: str
    factory: str
    ocr_variant: str


MODELS = {
    'argos': ModelSpec('速度优先', 'engine', 'ArgosEngine', 'tiny'),
    'plamo': ModelSpec('效果优先', 'plamo', 'PlamoEngine', 'small'),
}
DEFAULT_MODEL = 'argos'


def _spec(name):
    try:
        return MODELS[name]
    except (KeyError, TypeError) as exc:
        raise TsError(f'未知模型：{name}。请在交互终端运行 ts --models 重新选择默认模式。') from exc


def _module(name):
    spec = _spec(name)
    try:
        return importlib.import_module(f'.{spec.module}', __package__)
    except ImportError as exc:
        raise TsError(f'模型 {name} 的组件不可用：{exc}') from exc


def config_path():
    base = os.environ.get('XDG_CONFIG_HOME')
    if base:
        directory = Path(base).expanduser()
        if not directory.is_absolute():
            raise TsError('XDG_CONFIG_HOME 必须是绝对路径。')
    else:
        directory = Path.home() / '.config'
    return directory / 'ts' / 'config.json'


def _read_config():
    path = config_path()
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TsError(f'无法读取模型配置 {path}：{exc}') from exc
    if not isinstance(value, dict):
        raise TsError(f'模型配置格式无效：{path}。请修复或删除该文件。')
    return value


def default_model(*, allow_invalid=False):
    name = _read_config().get('model', DEFAULT_MODEL)
    try:
        _spec(name)
    except TsError:
        if allow_invalid:
            return None
        raise
    return name


def resolve_model(explicit=None):
    if explicit is not None:
        _spec(explicit)
        return explicit
    return default_model()


def available(name):
    from .ocr import available as ocr_available

    try:
        module = _module(name)
        if name != 'argos':
            ready, detail = module.available()
            return ocr_available(_spec(name).ocr_variant) if ready else (ready, detail)
    except TsError as exc:
        return False, str(exc)
    try:
        pairs = {(pkg.from_code, pkg.to_code) for pkg in module.local_packages()
                 if pkg.type == 'translate' and hasattr(pkg, 'tokenizer')
                 and (pkg.package_path / 'model').is_dir()}
    except TsError as exc:
        return False, str(exc)
    missing = {('en', 'zh'), ('zh', 'en')} - pairs
    if missing:
        pairs_text = '、'.join(f'{source}→{target}' for source, target in sorted(missing))
        return False, f'缺少本地 {pairs_text} 模型；请在项目目录运行 ./install.sh 联网安装。'
    return ocr_available(_spec(name).ocr_variant)


def set_default(name):
    _spec(name)
    ready, detail = available(name)
    if not ready:
        raise TsError(f'模型 {name} 不可用：{detail}')
    path = config_path()
    config = _read_config()
    config['model'] = name
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.config-', delete=False) as file:
            temp_path = Path(file.name)
            json.dump(config, file, ensure_ascii=False, indent=2)
            file.write('\n')
        os.replace(temp_path, path)
    except OSError as exc:
        raise TsError(f'无法保存模型配置 {path}：{exc}') from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


@contextmanager
def open_translator(name, *, on_stage=None):
    spec = _spec(name)
    module = _module(name)
    translator = getattr(module, spec.factory)(on_stage=on_stage)
    try:
        yield translator
    finally:
        close = getattr(translator, 'close', None)
        if close is not None:
            close()
