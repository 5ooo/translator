import re

import pytest

from ts.text import bounded, translate_text


@pytest.fixture
def pipeline():
    calls = []
    def detect(text):
        calls.append(('detect', text))
        return 'zh' if re.search('[\u3400-\u9fff]', text) else 'en'
    def translate(text, source, target):
        calls.append(('translate', text, source, target))
        return f'<{source}:{text}>'
    return calls, detect, translate


def test_both_directions_use_detector(pipeline):
    calls, detect, translate = pipeline
    assert translate_text('Hello.\n你好。', detect, translate) == '<en:Hello.>\n<zh:你好。>'
    assert [c[2:] for c in calls if c[0] == 'translate'] == [('en', 'zh'), ('zh', 'en')]


def test_mixed_sentence(pipeline):
    calls, detect, translate = pipeline
    result = translate_text('请检查 network connection 后重试。', detect, translate)
    assert '<zh:请检查>' in result
    assert '<en:network connection>' in result
    assert '<zh:后重试。>' in result
    assert len([c for c in calls if c[0] == 'detect']) == 3


@pytest.mark.parametrize('technical', [
    '`print("hello")`', 'API', 'GPU', 'CUDA', '/home/user/a.py', './a/b', '../foo', '~/a.txt',
    r'C:\Users\a.py', 'https://example.org/a?q=x', '`foo_bar`', 'foo_bar()', 'foo_bar = 2',
    '/tmp/foo_bar', './foo_bar', 'foo_bar.py', 'docs/foo_bar', '$ grab_box',
    '    foo_bar\n', '\tgrab_box', 'getValue', 'src/ts/cli.py',
    'alice@example.com', 'main.py',
    '```python\nprint("hello")\n```\n', '~~~sh\nls -la\n~~~\n',
    '    print("hello")\n', '$ echo hello', 'git status',
])
def test_technical_content_is_unchanged(technical, pipeline):
    calls, detect, translate = pipeline
    assert translate_text(technical, detect, translate) == technical
    assert calls == []


def test_protection_does_not_eat_chinese_or_punctuation(pipeline):
    _, detect, translate = pipeline
    text = '访问 https://example.org/a。然后打开 /tmp/a.txt。'
    result = translate_text(text, detect, translate)
    assert 'https://example.org/a' in result
    assert '/tmp/a.txt' in result
    assert '<zh:。然后打开>' in result


def test_whitespace_and_digits(pipeline):
    _, detect, translate = pipeline
    assert translate_text('  Hello.  \n\n123\t\n', detect, translate) == '  <en:Hello.>  \n\n123\t\n'


def test_unclosed_fence_kept(pipeline):
    _, detect, translate = pipeline
    text = '```python\nprint("hello")'
    assert translate_text(text, detect, translate) == text


def test_long_blocks_do_not_lose_characters():
    text = 'long text ' * 500
    blocks = list(bounded(text))
    assert ''.join(blocks) == text
    assert all(len(b) <= 400 for b in blocks)


@pytest.mark.parametrize('text', [
    'I', 'I am ready.', 'A sample.', 'HELLO', 'HELLO WORLD',
    'python is easy to learn', 'git is useful', 'sudo is a command',
    'The value is 3.14, e.g. a sample.',
])
def test_ordinary_english_reaches_translation_intact(text, pipeline):
    calls, detect, translate = pipeline
    assert translate_text(text, detect, translate) == f'<en:{text}>'
    assert calls == [('detect', text), ('translate', text, 'en', 'zh')]


@pytest.mark.parametrize('technical', [
    'API', 'GPU', 'CUDA', 'foo_bar', 'getValue', 'ROS', 'ROS2', 'SLAM',
    'OTA', 'RGB', 'MD5', 'IMU', 'G1',
])
def test_technical_tokens_touching_chinese_bypass_models(technical, pipeline):
    calls, detect, translate = pipeline
    assert translate_text(f'检查{technical}后重试。', detect, translate) == (
        f'<zh:检查>{technical}<zh:后重试。>'
    )
    assert calls == [
        ('detect', '检查'), ('translate', '检查', 'zh', 'en'),
        ('detect', '后重试。'), ('translate', '后重试。', 'zh', 'en'),
    ]


@pytest.mark.parametrize('path', [
    '/home/张三/report.txt', r'C:\Users\张三\report.txt',
    '资料/报告.txt', './资料/报告.txt', '../资料/报告.txt', '~/资料/报告.txt',
    '/tmp/资料然后打开', '/home/张三/报告',
])
def test_unicode_paths_are_preserved_whole(path, pipeline):
    calls, detect, translate = pipeline
    assert translate_text(f'打开 {path}。', detect, translate) == f'<zh:打开> {path}。'
    assert calls == [('detect', '打开'), ('translate', '打开', 'zh', 'en')]


def test_filename_extension_ends_before_adjacent_chinese(pipeline):
    calls, detect, translate = pipeline
    assert translate_text('/home/张三/report.txt然后重试。', detect, translate) == (
        '/home/张三/report.txt<zh:然后重试。>'
    )
    assert calls == [('detect', '然后重试。'), ('translate', '然后重试。', 'zh', 'en')]


@pytest.mark.parametrize('command', [
    'git status', 'pip install package', 'pip3 install package',
    'python tool.py', 'python3 ./工具.py', "python -c 'print(1)'",
    'ls -la', 'sudo git status', 'sudo python tool.py', '$ echo hello',
    'npm install', 'docker run image', 'curl https://example.org',
    'export NAME=value',
])
def test_explicit_command_forms_bypass_models(command, pipeline):
    calls, detect, translate = pipeline
    assert translate_text(command, detect, translate) == command
    assert calls == []


@pytest.mark.parametrize('code', [
    '```python\nprint("hello")\n````\n',
    '````python\n```\nprint("hello")\n````\n',
    '~~~sh\necho hello\n~~~~\n',
    '``print(`hello`)``',
])
def test_matching_code_delimiters_preserve_whole_block(code, pipeline):
    calls, detect, translate = pipeline
    assert translate_text(code, detect, translate) == code
    assert calls == []


def test_mixed_long_prose_keeps_all_source_characters_and_directions():
    text = ('hello world ' * 60) + ('你好世界' * 120) + '\nHELLO WORLD'
    calls = []
    def detect(body):
        return 'zh' if re.search('[\u3400-\u9fff]', body) else 'en'
    def translate(body, source, target):
        calls.append((body, source, target))
        return body
    assert translate_text(text, detect, translate) == text
    assert all(len(body) <= 400 for body, _, _ in calls)
    assert all(target == ('zh' if source == 'en' else 'en') for _, source, target in calls)
    assert {source for _, source, _ in calls} == {'en', 'zh'}


def test_english_translation_separates_adjacent_technical_token():
    translations = {'检查': 'Check', '状态。': 'status.'}
    result = translate_text('检查API状态。', lambda _: 'zh',
                            lambda body, *_: translations[body])
    assert result == 'Check API status.'


@pytest.mark.parametrize(('prefix', 'technical'), [
    ('检查', 'API'), ('检查 ', '/tmp/a.py'), ('检查', '`print("hello")`'),
])
def test_english_translation_spaces_around_unchanged_technical_content(prefix, technical):
    translations = {'检查': 'Check it out.', '然后重试。': 'Then retry.'}
    result = translate_text(f'{prefix}{technical}然后重试。', lambda _: 'zh',
                            lambda body, *_: translations[body])
    assert result == f'Check it out. {technical} Then retry.'


def test_chinese_translation_does_not_add_spaces_around_code():
    translations = {'Check': '检查', 'status.': '状态。'}
    result = translate_text('Check`print("hello")`status.', lambda _: 'en',
                            lambda body, *_: translations[body])
    assert result == '检查`print("hello")`状态。'


def test_existing_boundary_whitespace_is_preserved():
    translations = {'检查': 'Check', '状态。': 'status.'}
    result = translate_text('检查\tAPI  状态。', lambda _: 'zh',
                            lambda body, *_: translations[body])
    assert result == 'Check\tAPI  status.'


@pytest.mark.parametrize(("source", "expected", "words"), [
    ("grab_box", "<en:grab box>", "grab box"),
    ("foo_bar", "<en:foo bar>", "foo bar"),
    (" grab_box\r\n", " <en:grab box>\r\n", "grab box"),
    ("  pick_up_box  \n", "  <en:pick up box>  \n", "pick up box"),
])
def test_standalone_snake_words_are_translated(source, expected, words, pipeline):
    calls, detect, translate = pipeline
    assert translate_text(source, detect, translate) == expected
    assert calls == [("detect", words), ("translate", words, "en", "zh")]
