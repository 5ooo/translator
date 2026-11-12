import io
import os
import shutil
import socket

import pytest

from ts.engine import ArgosEngine, Detector, local_packages
from ts.errors import TsError
from ts.inputs import ocr, run
from ts.text import translate_text

pytestmark = pytest.mark.integration


def unavailable(reason):
    if os.environ.get('TS_REQUIRE_INTEGRATION') == '1':
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*a, **k):
        raise AssertionError('集成测试禁止联网')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(socket, 'getaddrinfo', denied)


def test_real_detector():
    pytest.importorskip('langid') if os.environ.get('TS_REQUIRE_INTEGRATION') != '1' else None
    detect = Detector()
    assert detect('This is an English sentence.') == 'en'
    assert detect('这是一个中文句子。') == 'zh'


def test_real_argos_both_directions():
    try:
        pairs = {(p.from_code, p.to_code) for p in local_packages()}
    except TsError as exc:
        unavailable(str(exc))
    if not {('en', 'zh'), ('zh', 'en')}.issubset(pairs):
        unavailable('缺少真实 Argos 中英双向模型')
    engine = ArgosEngine()
    detect = Detector()
    for text in ('Hello world.', '这是一项测试。'):
        result = translate_text(text, detect, engine.translate)
        assert result.strip() and result != text
    assert any('\u3400' <= c <= '\u9fff' for c in translate_text('Hello world.', detect, engine.translate))
    result = translate_text('请检查 API 和 `/tmp/a.py`。 Hello world.', detect, engine.translate)
    assert 'API' in result and '`/tmp/a.py`' in result


def test_real_ocr():
    if not shutil.which('tesseract'):
        unavailable('未安装 Tesseract')
    langs = run(['tesseract', '--list-langs']).decode().split()
    if not {'eng', 'chi_sim'}.issubset(langs):
        unavailable('缺少 Tesseract eng+chi_sim')
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (900, 130), 'white')
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    if not os.path.isfile(font_path):
        unavailable('OCR 样例缺少 DejaVuSans 字体')
    ImageDraw.Draw(image).text((20, 25), 'Hello world', font=ImageFont.truetype(font_path, 64), fill='black')
    data = io.BytesIO()
    image.save(data, format='PNG')
    assert 'hello' in ocr(data.getvalue()).lower()


def test_real_mixed_ocr_reaches_detector():
    if not shutil.which('tesseract'):
        unavailable('未安装 Tesseract')
    langs = run(['tesseract', '--list-langs']).decode().split()
    if not {'eng', 'chi_sim'}.issubset(langs):
        unavailable('缺少 Tesseract eng+chi_sim')
    font_path = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
    if not os.path.isfile(font_path):
        unavailable('混合 OCR 样例缺少 NotoSansCJK 字体')
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (1000, 250), 'white')
    font = ImageFont.truetype(font_path, 52)
    draw = ImageDraw.Draw(image)
    draw.text((25, 20), 'Hello world', font=font, fill='black')
    draw.text((25, 120), '这是中文测试', font=font, fill='black')
    data = io.BytesIO()
    image.save(data, format='PNG')
    text = ocr(data.getvalue())
    assert 'hello' in text.lower()
    assert '中文' in text.replace(' ', '')
    detected = []
    detect = Detector()
    def spy(value):
        language = detect(value)
        detected.append(language)
        return language
    translate_text(text, spy, lambda value, source, target: value)
    assert set(detected) == {'en', 'zh'}
