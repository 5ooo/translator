import argparse
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / 'bin/ts'


def invoke(env, arguments=(), tty=False):
    master = slave = None
    try:
        if tty:
            master, slave = pty.openpty()
        command = ['bash', '--noprofile', '-ic', 'ts'] if tty and not arguments else [str(TS), *arguments]
        result = subprocess.run(command, env=env,
                                stdin=slave if tty else subprocess.DEVNULL,
                                capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
        return result.stdout
    finally:
        if master is not None:
            os.close(master)
            os.close(slave)


def verify(env, backend, data, mime, expected):
    if backend == 'x11':
        command = ['xclip', '-quiet', '-selection', 'clipboard', '-i', '-t', mime]
        listing = ['xclip', '-selection', 'clipboard', '-o', '-t', 'TARGETS']
    else:
        command = ['wl-copy', '--foreground', '--type', mime]
        listing = ['wl-paste', '--list-types']
    process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        process.stdin.write(data)
        process.stdin.close()
        for _ in range(30):
            result = subprocess.run(listing, env=env, capture_output=True, timeout=5)
            if result.returncode == 0 and mime.encode() in result.stdout:
                break
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode(errors='replace'))
            time.sleep(0.1)
        else:
            raise RuntimeError('等待测试剪贴板内容超时')
        actual = invoke(env, tty=True)
        if actual != expected:
            raise AssertionError(f'{backend} {mime}: expected {expected!r}, got {actual!r}')
        print(f'{backend} {mime}: PASS {actual.decode().strip()!r}', flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stderr.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['x11', 'wayland'], required=True)
    parser.add_argument('--display', required=True, help='本任务创建的测试显示器名称')
    parser.add_argument('--runtime-dir', help='Wayland 测试会话的 XDG_RUNTIME_DIR')
    args = parser.parse_args()
    env = os.environ.copy()
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    env['PATH'] = str(ROOT / '.runtime/system/usr/bin') + os.pathsep + env['PATH']
    if args.backend == 'x11':
        env['DISPLAY'] = args.display
    else:
        if not args.runtime_dir:
            parser.error('Wayland 测试需要 --runtime-dir')
        env['WAYLAND_DISPLAY'] = args.display
        env['XDG_RUNTIME_DIR'] = args.runtime_dir
    text = 'The network is ready.'
    expected = invoke(env, ['--text', text])
    verify(env, args.backend, text.encode(), 'UTF8_STRING' if args.backend == 'x11' else 'text/plain;charset=utf-8', expected)
    from PIL import Image, ImageDraw, ImageFont
    with tempfile.TemporaryDirectory(prefix='ts-clipboard-') as directory:
        image = Image.new('RGB', (1000, 250), 'white')
        font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 52)
        draw = ImageDraw.Draw(image)
        draw.text((25, 20), 'Hello world', font=font, fill='black')
        draw.text((25, 120), '这是中文测试', font=font, fill='black')
        path = Path(directory) / 'mixed.png'
        image.save(path)
        expected = invoke(env, ['--image', str(path)])
        verify(env, args.backend, path.read_bytes(), 'image/png', expected)


if __name__ == '__main__':
    main()
