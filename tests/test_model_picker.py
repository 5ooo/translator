import errno
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time

import pytest


CHILD = '''
import os
from ts import cli, models

def available(name):
    ready = name != 'plamo' or os.environ.get('TS_TEST_MISSING') != '1'
    return ready, '' if ready else '缺少模型'

cli.available = available
models.available = available
raise SystemExit(cli.main(['--models'] + (['--plain'] if os.environ.get('TS_TEST_PLAIN') else [])))
'''
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


class Menu:
    def __init__(self, tmp_path, *, selected='argos', missing=False, plain=False, no_color=False, dumb=False):
        try:
            self.master, self.slave = pty.openpty()
        except OSError as exc:
            pytest.skip(f'无法创建伪终端：{exc}')
        self.before = termios.tcgetattr(self.slave)
        self.config = tmp_path / 'config/ts/config.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({'model': selected, 'other': 'keep'}), encoding='utf-8')
        env = os.environ.copy()
        env['XDG_CONFIG_HOME'] = str(tmp_path / 'config')
        env['TERM'] = 'dumb' if dumb else 'xterm-256color'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.pop('NO_COLOR', None)
        if missing:
            env['TS_TEST_MISSING'] = '1'
        if plain:
            env['TS_TEST_PLAIN'] = '1'
        if no_color:
            env['NO_COLOR'] = ''
        self.process = subprocess.Popen([sys.executable, '-c', CHILD], stdin=self.slave,
                                        stdout=self.slave, stderr=self.slave, env=env,
                                        start_new_session=True)
        self.output = b''

    def read_available(self, timeout=0.1):
        ready, _, _ = select.select([self.master], [], [], timeout)
        if ready:
            try:
                self.output += os.read(self.master, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise

    def text(self):
        return ANSI.sub('', self.output.decode('utf-8', errors='replace')).replace('\r\n', '\n')

    def wait_for(self, text):
        deadline = time.monotonic() + 8
        while text not in self.text():
            self.read_available()
            if self.process.poll() is not None:
                self.read_available(0)
                pytest.fail(f'选择界面提前退出：{self.text()}')
            if time.monotonic() > deadline:
                pytest.fail(f'等待选择界面超时，当前输出：{self.text()}')

    def send(self, data):
        os.write(self.master, data)

    def finish(self, code=0):
        assert self.process.wait(timeout=8) == code
        while select.select([self.master], [], [], 0)[0]:
            self.read_available(0)
        assert termios.tcgetattr(self.slave) == self.before
        return self.text()

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        os.close(self.master)
        os.close(self.slave)


@pytest.fixture
def menu(tmp_path):
    created = []

    def make(**kwargs):
        instance = Menu(tmp_path, **kwargs)
        created.append(instance)
        return instance

    yield make
    for instance in created:
        instance.close()


@pytest.mark.parametrize(('initial', 'key', 'focus', 'expected'), [
    ('argos', b'\x1b[B', '>   效果优先', 'plamo'),
    ('plamo', b'\x1b[A', '>   速度优先', 'argos'),
])
def test_arrow_and_enter_save_selected_mode(menu, initial, key, focus, expected):
    instance = menu(selected=initial)
    instance.wait_for('Esc 取消')
    instance.send(key)
    instance.wait_for(focus)
    instance.send(b'\r')
    instance.finish()
    assert json.loads(instance.config.read_text(encoding='utf-8')) == {'model': expected, 'other': 'keep'}


def test_escape_cancels_without_changing_config(menu):
    instance = menu()
    original = instance.config.read_bytes()
    instance.wait_for('Esc 取消')
    instance.output = b''
    instance.send(b'\x1b[B')
    instance.wait_for('>   效果优先')
    assert '* 速度优先' in instance.text()
    instance.send(b'\x1b')
    assert '已取消' in instance.finish()
    assert b'\x1b[?25h' in instance.output
    assert instance.config.read_bytes() == original


@pytest.mark.parametrize('old_model', ['qwen', 'm2m', None, ['invalid'], {'unexpected': 1}])
def test_invalid_saved_mode_can_be_replaced_in_menu(menu, old_model):
    instance = menu(selected=old_model)
    instance.wait_for('当前设置无效')
    assert '* 速度优先' not in instance.text()
    assert '* 效果优先' not in instance.text()
    instance.send(b'\x1b[B')
    instance.wait_for('>   效果优先')
    instance.send(b'\r')
    instance.finish()
    assert json.loads(instance.config.read_text(encoding='utf-8')) == {'model': 'plamo', 'other': 'keep'}


def test_invalid_saved_mode_can_be_cancelled_without_overwrite(menu):
    instance = menu(selected='qwen')
    original = instance.config.read_bytes()
    instance.wait_for('当前设置无效')
    instance.send(b'\x1b')
    instance.finish()
    assert instance.config.read_bytes() == original


def test_enter_on_current_mode_leaves_config_unchanged(menu):
    instance = menu()
    original = instance.config.read_bytes()
    instance.wait_for('Esc 取消')
    instance.send(b'\r')
    assert '* 速度优先' in instance.finish()
    assert instance.config.read_bytes() == original


def test_arrow_sequence_may_arrive_in_parts(menu):
    instance = menu()
    instance.wait_for('Esc 取消')
    for part in (b'\x1b', b'[', b'B'):
        instance.send(part)
        time.sleep(0.02)
    instance.wait_for('>   效果优先')
    instance.send(b'\r')
    instance.finish()
    assert json.loads(instance.config.read_text(encoding='utf-8'))['model'] == 'plamo'


def test_unavailable_mode_stays_in_menu(menu):
    instance = menu(missing=True)
    original = instance.config.read_bytes()
    instance.wait_for('Esc 取消')
    instance.send(b'\x1b[B')
    instance.wait_for('>   效果优先')
    instance.send(b'\r')
    instance.wait_for('该模式不可用')
    assert instance.process.poll() is None
    assert instance.config.read_bytes() == original
    instance.send(b'\x1b')
    instance.finish()


def test_interrupt_restores_terminal_without_saving(menu):
    instance = menu()
    original = instance.config.read_bytes()
    instance.wait_for('Esc 取消')
    instance.process.send_signal(signal.SIGINT)
    instance.finish(code=130)
    assert b'\x1b[?25h' in instance.output
    assert instance.config.read_bytes() == original


def test_no_color_still_allows_keyboard_selection(menu):
    instance = menu(no_color=True)
    instance.wait_for('Esc 取消')
    instance.send(b'\x1b[B')
    instance.wait_for('>   效果优先')
    instance.send(b'\r')
    instance.finish()
    assert json.loads(instance.config.read_text(encoding='utf-8'))['model'] == 'plamo'
    assert not re.search(rb'\x1b\[[0-9;]*m', instance.output)


@pytest.mark.parametrize('mode', ['plain', 'dumb'])
def test_noninteractive_mode_lists_without_waiting_for_input(menu, mode):
    instance = menu(**{mode: True})
    assert instance.finish() == '* 速度优先\n  效果优先\n'
