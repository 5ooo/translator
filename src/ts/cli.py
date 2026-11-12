import argparse
import sys

from .engine import ArgosEngine, Detector, check, install_model
from .errors import TsError
from .events import Stage
from .inputs import read_input
from .models import MODELS, available, default_model, open_translator, resolve_model, set_default
from .presentation import Presenter
from .text import translate_text


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ts', description='离线中英翻译，支持文字、图片与剪贴板')
    parser.add_argument('input', nargs='*', help='文字或单个图片路径')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--text', help='强制输入为文字')
    group.add_argument('--image', help='强制输入为图片文件路径')
    group.add_argument('--check', action='store_true', help='检查系统依赖与所选本地模型')
    group.add_argument('--install-model', metavar='FILE', help='安装本地 .argosmodel 包，不联网')
    group.add_argument('--models', action='store_true', help='列出可选模型及其可用状态')
    group.add_argument('--set-model', choices=tuple(MODELS), metavar='NAME', help='设置默认翻译模型')
    parser.add_argument('--model', choices=tuple(MODELS), metavar='NAME', help='仅本次使用指定模型')
    parser.add_argument('--plain', action='store_true', help='使用纯文本输出，不显示颜色与动画')
    args = parser.parse_args(argv)
    if args.input and any((args.text is not None, args.image is not None, args.check,
                           args.install_model is not None, args.models, args.set_model is not None)):
        parser.error('位置参数不能与 --text、--image 或管理命令混用')
    if args.model and (args.models or args.set_model is not None or args.install_model is not None):
        parser.error('--model 不能与 --models、--set-model 或 --install-model 混用')
    try:
        if args.models:
            selected = default_model()
            for name in MODELS:
                ready, _ = available(name)
                current = '（默认）' if name == selected else ''
                print(f'{name}  {"可用" if ready else "不可用"}{current}')
            return 0
        if args.set_model is not None:
            set_default(args.set_model)
            print(f'默认翻译模型已设为 {args.set_model}。')
            return 0
        if args.install_model is not None:
            install_model(args.install_model)
            print('本地模型安装完成。')
            return 0
        selected = resolve_model(args.model)
        if args.check:
            ok, messages = check() if selected == 'argos' else check(selected)
            print('\n'.join(messages))
            return 0 if ok else 1
        with Presenter(sys.stdout, sys.stderr, plain=args.plain) as ui:
            source = read_input(args.input, args.text, args.image, sys.stdin, on_stage=ui.stage)
            with open_translator(selected, on_stage=ui.stage) as engine:
                detector = Detector()

                def detect(text):
                    ui.stage(Stage.DETECT)
                    return detector(text)

                result = translate_text(source.text, detect, engine.translate)
            ui.result(source, result)
        return 0
    except TsError as exc:
        print(f'ts：{exc}', file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
