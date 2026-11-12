import os
import socket

import pytest

from ts.engine import Detector
from ts.plamo import PlamoEngine, available
from ts.text import translate_text


pytestmark = pytest.mark.integration


@pytest.fixture
def local_only(monkeypatch):
    connect = socket.socket.connect
    resolve = socket.getaddrinfo

    def checked_connect(sock, address):
        if isinstance(address, tuple) and address[0] == '127.0.0.1':
            return connect(sock, address)
        raise AssertionError('PLaMo 集成测试禁止外部连接')

    def checked_resolve(host, *args, **kwargs):
        if host == '127.0.0.1':
            return resolve(host, *args, **kwargs)
        raise AssertionError('PLaMo 集成测试禁止外部 DNS')

    monkeypatch.setattr(socket.socket, 'connect', checked_connect)
    monkeypatch.setattr(socket, 'getaddrinfo', checked_resolve)


def test_real_plamo_bidirectional_and_protected_text(local_only):
    ready, reason = available()
    if not ready:
        if os.environ.get('TS_REQUIRE_PLAMO') == '1':
            pytest.fail(reason)
        pytest.skip(reason)
    engine = PlamoEngine()
    detect = Detector()
    try:
        english = translate_text('The robot should grab the box.', detect, engine.translate)
        chinese = translate_text('请检查网络连接后重试。', detect, engine.translate)
        mixed = translate_text('Run `python3 main.py` to start the server.', detect, engine.translate)
    finally:
        engine.close()
    assert '机器人' in english and '抓' in english and any(x in english for x in ('盒子', '箱子'))
    assert 'network' in chinese.lower() and ('try' in chinese.lower() or 'retry' in chinese.lower())
    assert '`python3 main.py`' in mixed
