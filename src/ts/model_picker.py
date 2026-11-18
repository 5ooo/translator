import os
import select
import termios
import tty
from dataclasses import dataclass
from typing import TextIO

from rich.console import Console
from rich.live import Live
from rich.text import Text


@dataclass(frozen=True)
class ModelOption:
    name: str
    title: str
    available: bool


def _key(fd: int) -> str:
    first = os.read(fd, 1)
    if first in (b'\r', b'\n'):
        return 'enter'
    if first in (b'', b'\x04'):
        return 'cancel'
    if first != b'\x1b':
        return 'other'
    if not select.select([fd], [], [], 0.1)[0]:
        return 'cancel'
    second = os.read(fd, 1)
    if second not in (b'[', b'O'):
        return 'cancel'
    if not select.select([fd], [], [], 0.1)[0]:
        return 'other'
    return {b'A': 'up', b'B': 'down'}.get(os.read(fd, 1), 'other')


def _screen(options: list[ModelOption], current: str | None, focus: int,
            message: str, styled: bool) -> Text:
    text = Text()
    text.append('↑↓ 选择  Enter 确认  Esc 取消\n', style='dim' if styled else None)
    for index, option in enumerate(options):
        focused = index == focus
        active = option.name == current
        text.append('> ' if focused else '  ', style='bold cyan' if focused and styled else None)
        text.append('* ' if active else '  ', style='cyan' if active and styled else None)
        style = 'bold cyan' if active and focused else 'cyan' if active else 'bold' if focused else None
        text.append(option.title, style=style if styled else None)
        if not option.available:
            text.append('（不可用）', style='dim' if styled else None)
        text.append('\n')
    if message:
        text.append(message, style='red' if styled else None)
    return text


def choose_model(stdin: TextIO, console: Console, options: list[ModelOption],
                 current: str | None, *, styled: bool) -> str | None:
    fd = stdin.fileno()
    original = termios.tcgetattr(fd)
    focus = next((index for index, option in enumerate(options) if option.name == current), 0)
    message = '当前设置无效，请重新选择。' if current is None else ''
    try:
        tty.setcbreak(fd)
        with Live(_screen(options, current, focus, message, styled), console=console,
                  auto_refresh=False, transient=True, redirect_stdout=False,
                  redirect_stderr=False) as live:
            while True:
                key = _key(fd)
                if key == 'cancel':
                    return None
                if key in ('up', 'down'):
                    focus = (focus + (-1 if key == 'up' else 1)) % len(options)
                    message = ''
                elif key == 'enter':
                    if options[focus].available:
                        return options[focus].name
                    message = '该模式不可用，请选择其他模式。'
                else:
                    continue
                live.update(_screen(options, current, focus, message, styled), refresh=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)
