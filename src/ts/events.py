from enum import Enum
from typing import Callable


class Stage(str, Enum):
    READ = 'read'
    CLIPBOARD = 'clipboard'
    OCR = 'ocr'
    DETECT = 'detect'
    MODEL = 'model'
    TRANSLATE = 'translate'


StageObserver = Callable[[Stage], None]


def emit(observer: StageObserver | None, stage: Stage) -> None:
    if observer is not None:
        observer(stage)
