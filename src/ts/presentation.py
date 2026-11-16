import os
from typing import TextIO

from rich.console import Console
from rich.status import Status
from rich.text import Text

from .events import Stage
from .inputs import InputResult


LABELS = {
    Stage.READ: '读取输入',
    Stage.CLIPBOARD: '读取剪贴板',
    Stage.OCR: '识别图片文字',
    Stage.DETECT: '识别语言',
    Stage.MODEL: '载入本地模型',
    Stage.TRANSLATE: '翻译中',
}


class Presenter:
    def __init__(self, stdout: TextIO, stderr: TextIO, *, plain: bool = False):
        self.stdout = stdout
        self.styled = (not plain and stdout.isatty() and 'NO_COLOR' not in os.environ
                       and os.environ.get('TERM', '') not in ('', 'dumb', 'unknown'))
        self.console = Console(file=stdout, highlight=False, markup=False)
        self.status = None
        if self.styled and stderr.isatty():
            self.status = Status('', console=Console(file=stderr, highlight=False, markup=False),
                                 spinner='dots', spinner_style='cyan', refresh_per_second=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        if self.status is not None:
            self.status.stop()

    def stage(self, stage: Stage) -> None:
        if self.status is not None:
            self.status.update(Text(LABELS[stage], style='dim'))
            self.status.start()

    def model_option(self, title: str, *, selected: bool, available: bool) -> None:
        prefix = '* ' if selected else '  '
        suffix = '' if available else '（不可用）'
        line = prefix + title + suffix
        if selected and self.styled:
            self.console.print(Text(line, style='cyan'))
        else:
            self.stdout.write(line + '\n')

    def result(self, source: InputResult, translated: str) -> None:
        self.stop()
        if not self.styled:
            if source.origin == 'image':
                self.stdout.write('原文：\n' + source.text)
                if not source.text.endswith('\n'):
                    self.stdout.write('\n')
                self.stdout.write('\n译文：\n')
            self.stdout.write(translated)
            if not translated.endswith('\n'):
                self.stdout.write('\n')
            return
        original = Text('原文：' + source.text.rstrip('\n'), style='dim', overflow='fold')
        width = self.console.width
        self.console.print(original, width=width)
        if len(original.wrap(self.console, width)) > 1:
            self.console.print()
        translation = Text(overflow='fold')
        translation.append('译文：', style='bold cyan')
        translation.append(translated.rstrip('\n'))
        self.console.print(translation)
