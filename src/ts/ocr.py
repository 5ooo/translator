"""Offline PP-OCRv6 models used by the two translation modes."""

import importlib.util
import io
import os
from pathlib import Path

from .errors import TsError


ROOT = Path(__file__).resolve().parents[2]
TINY_FILES = ('PP-OCRv6_det_tiny.onnx', 'PP-OCRv6_rec_tiny.onnx')
SMALL_FILES = ('PP-OCRv6_det_small.onnx', 'PP-OCRv6_rec_small.onnx')


def model_files(variant):
    if variant == 'tiny':
        directories = []
        if data_home := os.environ.get('XDG_DATA_HOME'):
            directories.append(Path(data_home).expanduser() / 'ts/models/ocr')
        directories.append(ROOT / '.runtime/data/ts/models/ocr')
        for directory in directories:
            paths = tuple(directory / name for name in TINY_FILES)
            if all(path.is_file() and os.access(path, os.R_OK) for path in paths):
                return paths
        raise TsError('缺少 PP-OCRv6 Tiny 模型，请在项目目录运行 ./install.sh 联网安装。')
    if variant == 'small':
        spec = importlib.util.find_spec('rapidocr')
        if spec is not None and spec.submodule_search_locations:
            directory = Path(next(iter(spec.submodule_search_locations))) / 'models'
            paths = tuple(directory / name for name in SMALL_FILES)
            if all(path.is_file() and os.access(path, os.R_OK) for path in paths):
                return paths
        raise TsError('缺少 PP-OCRv6 Small 模型，请在项目目录运行 ./install.sh 联网安装。')
    raise TsError(f'未知 OCR 模型：{variant}')


def available(variant):
    for module in ('rapidocr', 'onnxruntime', 'cv2'):
        if importlib.util.find_spec(module) is None:
            return False, f'缺少 {module}，请运行 ./install.sh 安装。'
    try:
        model_files(variant)
    except TsError as exc:
        return False, str(exc)
    return True, f'PP-OCRv6 {variant.title()} 本地模型可用'


class OCREngine:
    def __init__(self, variant):
        self.variant = variant
        self.engine = None

    def _engine(self):
        if self.engine is not None:
            return self.engine
        det, rec = model_files(self.variant)
        try:
            import onnxruntime
            from rapidocr import ModelType, OCRVersion, RapidOCR
        except ImportError as exc:
            raise TsError(f'缺少 OCR 运行依赖，请运行 ./install.sh 安装：{exc}') from exc
        onnxruntime.disable_telemetry_events()
        model_type = ModelType.TINY if self.variant == 'tiny' else ModelType.SMALL
        params = {
            'Global.use_cls': False,
            'Global.log_level': 'error',
            'EngineConfig.onnxruntime.intra_op_num_threads': 4,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
            'Det.ocr_version': OCRVersion.PPOCRV6,
            'Rec.ocr_version': OCRVersion.PPOCRV6,
            'Det.model_type': model_type,
            'Rec.model_type': model_type,
            'Det.model_path': str(det),
            'Rec.model_path': str(rec),
        }
        self.engine = RapidOCR(params=params)
        return self.engine

    def recognize(self, data):
        try:
            from PIL import Image, UnidentifiedImageError
        except ImportError as exc:
            raise TsError('缺少 Pillow，请安装项目依赖。') from exc
        try:
            with Image.open(io.BytesIO(data)) as source:
                image = source.convert('RGB')
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise TsError(f'无法解码图片：{exc}') from exc
        try:
            result = self._engine()(image, use_det=True, use_cls=False, use_rec=True)
            text = '\n'.join(result.txts or ())
            if not text.strip():
                raise TsError('图片中没有识别出文字。')
            return text
        except TsError:
            raise
        except Exception as exc:
            raise TsError(f'图片文字识别失败：{exc}') from exc
        finally:
            image.close()


def recognize(data, variant):
    return OCREngine(variant).recognize(data)
