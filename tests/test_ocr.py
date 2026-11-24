import io

import pytest
from PIL import Image

from ts import ocr
from ts.errors import TsError


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (20, 20), 'white').save(output, format='PNG')
    return output.getvalue()


def test_tiny_model_files_are_required_and_never_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, 'ROOT', tmp_path)
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'empty'))
    with pytest.raises(TsError, match='缺少 PP-OCRv6 Tiny'):
        ocr.recognize(image_bytes(), 'tiny')
    assert not (tmp_path / '.runtime').exists()


def test_invalid_input_is_reported_before_model_loading():
    with pytest.raises(TsError, match='无法解码图片'):
        ocr.recognize(b'not an image', 'small')


def test_tiny_model_path_falls_back_to_project(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, 'ROOT', tmp_path)
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'empty'))
    directory = tmp_path / '.runtime/data/ts/models/ocr'
    directory.mkdir(parents=True)
    for name in ocr.TINY_FILES:
        (directory / name).write_bytes(b'model')
    assert ocr.model_files('tiny') == tuple(directory / name for name in ocr.TINY_FILES)


def test_local_recognition_creates_new_engine_each_time(monkeypatch):
    created = []

    class FakeEngine:
        def __init__(self, variant):
            created.append(variant)

        def recognize(self, data):
            return data.decode()

    monkeypatch.setattr(ocr, 'OCREngine', FakeEngine)
    assert ocr.recognize(b'first', 'tiny') == 'first'
    assert ocr.recognize(b'second', 'tiny') == 'second'
    assert created == ['tiny', 'tiny']
