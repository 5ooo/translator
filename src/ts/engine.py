import importlib.util
import shutil

from .errors import TsError
from .events import Stage, StageObserver, emit
from .inputs import run


class Detector:
    def __init__(self):
        self.identifier = None

    def __call__(self, text):
        if self.identifier is None:
            try:
                from langid.langid import LanguageIdentifier, model
            except ImportError as exc:
                raise TsError('缺少 langid，请安装项目依赖。') from exc
            self.identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
            self.identifier.set_languages(['en', 'zh'])
        return self.identifier.classify(text)[0]


def local_packages():
    try:
        from argostranslate import package
        return package.get_installed_packages()
    except Exception as exc:
        raise TsError(f'无法读取 Argos 本地模型，请检查依赖与模型目录：{exc}') from exc


class ArgosEngine:
    def __init__(self, *, on_stage: StageObserver | None = None):
        self.loaded = {}
        self.on_stage = on_stage

    def translate(self, text, source, target):
        key = (source, target)
        try:
            if key not in self.loaded:
                emit(self.on_stage, Stage.MODEL)
                import ctranslate2
                pkg = next((p for p in local_packages() if p.type == 'translate' and
                            (p.from_code, p.to_code) == key), None)
                if pkg is None:
                    raise TsError(f'缺少本地 {source}→{target} 模型，请在项目目录运行 ./install.sh 联网安装。')
                if not hasattr(pkg, 'tokenizer') or not (pkg.package_path / 'model').is_dir():
                    raise TsError(f'{source}→{target} 模型格式不支持或不完整。')
                self.loaded[key] = (pkg, ctranslate2.Translator(str(pkg.package_path / 'model'), device='cpu'))
            emit(self.on_stage, Stage.TRANSLATE)
            pkg, translator = self.loaded[key]
            prefix = pkg.target_prefix
            result = translator.translate_batch(
                [pkg.tokenizer.encode(text)],
                target_prefix=[[prefix]] if prefix else None,
                beam_size=4, replace_unknowns=True,
            )[0]
            output = pkg.tokenizer.decode(result.hypotheses[0])
            if prefix and output.startswith(prefix):
                output = output[len(prefix):]
            if not output.strip():
                raise TsError('本地模型返回了空译文。')
            return output.strip()
        except TsError:
            raise
        except Exception as exc:
            raise TsError(f'Argos 本地推理失败：{exc}') from exc


def check(model='argos'):
    messages = []
    ok = True
    dependencies = ('langid', 'PIL')
    if model == 'argos':
        dependencies += ('argostranslate', 'ctranslate2')
    for name in dependencies:
        present = importlib.util.find_spec(name) is not None
        messages.append(f'{name}: {"已安装" if present else "缺失"}')
        ok &= present
    try:
        langs = run(['tesseract', '--list-langs']).decode().split()
        present = {'eng', 'chi_sim'}.issubset(langs)
        messages.append(f'Tesseract eng+chi_sim: {"已安装" if present else "缺失语言包"}')
        ok &= present
    except TsError as exc:
        messages.append(str(exc))
        ok = False
    if model == 'argos':
        try:
            pairs = {(p.from_code, p.to_code) for p in local_packages() if p.type == 'translate'
                     and hasattr(p, 'tokenizer') and (p.package_path / 'model').is_dir()}
            for pair in [('en', 'zh'), ('zh', 'en')]:
                present = pair in pairs
                messages.append(f'{pair[0]}→{pair[1]} 模型: {"已安装" if present else "缺失"}')
                ok &= present
        except TsError as exc:
            messages.append(str(exc))
            ok = False
    else:
        from .models import available
        try:
            present, detail = available(model)
            messages.append(f'{model} 模型: {"可用" if present else "不可用"}（{detail}）')
            ok &= present
        except TsError as exc:
            messages.append(str(exc))
            ok = False
    for tool in ('wl-paste', 'xclip'):
        messages.append(f'{tool}: {"已安装" if shutil.which(tool) else "未安装（对应剪贴板不可用）"}')
    return bool(ok), messages
