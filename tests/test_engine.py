from pathlib import Path
import sys
from types import SimpleNamespace

from ts import engine
from ts.events import Stage


def test_argos_local_inference_and_cache(monkeypatch, tmp_path):
    (tmp_path / 'model').mkdir()
    seen = []
    tokenizer = SimpleNamespace(encode=lambda text: [text], decode=lambda tokens: ''.join(tokens))
    pkg = SimpleNamespace(type='translate', from_code='en', to_code='zh',
                          package_path=tmp_path, target_prefix='__zh__', tokenizer=tokenizer)
    monkeypatch.setattr(engine, 'local_packages', lambda: [pkg])
    class Translator:
        def __init__(self, path, device):
            assert stages == [Stage.MODEL]
            seen.append((path, device))
        def translate_batch(self, tokens, **kwargs):
            assert stages[-1] == Stage.TRANSLATE
            assert tokens == [['Hello']]
            assert kwargs['target_prefix'] == [['__zh__']]
            return [SimpleNamespace(hypotheses=[['__zh__你好']])]
    monkeypatch.setitem(sys.modules, 'ctranslate2', SimpleNamespace(Translator=Translator))
    stages = []
    translator = engine.ArgosEngine(on_stage=stages.append)
    assert translator.translate('Hello', 'en', 'zh') == '你好'
    assert translator.translate('Hello', 'en', 'zh') == '你好'
    assert seen == [(str(tmp_path / 'model'), 'cpu')]
    assert stages == [Stage.MODEL, Stage.TRANSLATE, Stage.TRANSLATE]
