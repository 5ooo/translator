import re

ACRONYMS = frozenset({
    'API', 'GPU', 'CUDA', 'CLI', 'URL', 'HTTP', 'HTTPS', 'JSON', 'XML', 'SQL',
    'CPU', 'RAM', 'SDK', 'TCP', 'UDP', 'SSH', 'DNS', 'UTF', 'ASCII', 'PDF',
    'HTML', 'CSS', 'ROS', 'ROS2', 'SLAM', 'OTA', 'RGB', 'MD5', 'IMU', 'G1',
})
COMMAND_FORMS = (
    r'git[ \t]+(?:status|diff|log|show|add|commit|push|pull|fetch|clone|checkout|switch|branch|merge|rebase|reset|restore|stash|tag|remote|init)\b',
    r'pip3?[ \t]+(?:install|uninstall|list|show|freeze|check|download|wheel|cache|config)\b',
    r'python3?[ \t]+(?:-[A-Za-z]|[^\s`<>]+\.py(?:[ \t]|$))',
    r'npm[ \t]+(?:install|ci|run|test|start|build|update|uninstall|list|exec)\b',
    r'docker[ \t]+(?:run|build|pull|push|ps|images|exec|logs|stop|start|rm|rmi|compose|inspect)\b',
    r'(?:git|pip3?|npm|docker|ls|curl|wget)[ \t]+-[A-Za-z-]',
    r'(?:curl|wget)[ \t]+https?://',
    r'cd[ \t]+(?:/|\./|\.\./|~/)',
    r'export[ \t]+[A-Za-z_][A-Za-z0-9_]*=',
)
ASCII_LEFT = r'(?<![A-Za-z0-9_])'
ASCII_RIGHT = r'(?![A-Za-z0-9_])'
EXTENSIONS = r'(?:py|js|ts|json|yaml|yml|toml|txt|md|sh|cpp|h|png|jpg|pdf)'
PATH_BODY = r'[^\s`<>"\x27，。！？；、,;:!?()\[\]{}]'
PATH_ROOT = r'(?:[A-Za-z]:[\\/]|/|\./|\.\./|~/)'
PATH_SEGMENT = r'[^\s`<>"\x27，。！？；、,;:!?()\[\]{}/\\]+'
FILE_END = r'(?![A-Za-z0-9_.])'

PROTECTED = re.compile(
    r'(?:^[ \t]{0,3}(?P<backticks>`{3,})[^\n]*(?:\n|\Z).*?(?:^[ \t]{0,3}(?P=backticks)`*[ \t]*(?:\n|$)|\Z))'
    r'|(?:^[ \t]{0,3}(?P<tildes>~{3,})[^\n]*(?:\n|\Z).*?(?:^[ \t]{0,3}(?P=tildes)~*[ \t]*(?:\n|$)|\Z))'
    r'|(?:^(?: {4}|\t)[^\n]*(?:\n|$))'
    rf'|(?:^[ \t]*(?:\$ |(?:sudo[ \t]+)?(?:{"|".join(COMMAND_FORMS)}))[^\n]*)'
    r'|(?:(?<!`)(?P<inline>`+)(?!`)[^\n]*?(?<!`)(?P=inline)(?!`))'
    r'|(?:(?:https?|ftp)://[^\s<>`\u3400-\u9fff。，！？；、]+(?<![.,;:!?)]))'
    rf'|(?:{ASCII_LEFT}{PATH_ROOT}{PATH_BODY}+?\.{EXTENSIONS}{FILE_END})'
    rf'|(?:{ASCII_LEFT}{PATH_ROOT}{PATH_BODY}+(?<![.]))'
    rf'|(?:{ASCII_LEFT}{PATH_SEGMENT}(?:/{PATH_SEGMENT})+?\.{EXTENSIONS}{FILE_END})'
    rf'|(?:{ASCII_LEFT}{PATH_SEGMENT}(?:/{PATH_SEGMENT})+(?<![.]))'
    rf'|(?:{ASCII_LEFT}[A-Za-z0-9_\u3400-\u9fff-]+\.{EXTENSIONS}{FILE_END})'
    rf'|(?:{ASCII_LEFT}[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{{2,}}{ASCII_RIGHT})'
    rf'|(?:{ASCII_LEFT}[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+{ASCII_RIGHT})'
    rf'|(?:{ASCII_LEFT}[a-z]+(?:[A-Z][A-Za-z0-9]*)+{ASCII_RIGHT})'
    rf'|(?:{ASCII_LEFT}(?:{"|".join(sorted(ACRONYMS, key=lambda word: (-len(word), word)))}|[A-Z]+[0-9]+[A-Z0-9]*|[A-Z][A-Z0-9]*(?:[-+][A-Z0-9]+)+){ASCII_RIGHT})',
    re.MULTILINE | re.DOTALL,
)
HAN = r'\u3400-\u9fff\U00020000-\U0002fa1f'
SCRIPTS = re.compile(rf'[{HAN}]+[^A-Za-z{HAN}]*|[A-Za-z]+[^\u3400-\u9fff\U00020000-\U0002fa1f]*|[^A-Za-z{HAN}]+')


def bounded(text, limit=400):
    while len(text) > limit:
        end = text.rfind(' ', 0, limit + 1)
        if end <= 0:
            end = limit
        yield text[:end]
        text = text[end:]
    if text:
        yield text


def translate_piece(text, detect, translate):
    match = re.fullmatch(r'(\s*)(.*?)(\s*)', text, re.DOTALL)
    leading, body, trailing = match.groups()
    if not re.search(rf'[A-Za-z{HAN}]', body):
        return text
    source = detect(body)
    target = 'zh' if source == 'en' else 'en'
    return leading + translate(body, source, target) + trailing


def translate_prose(text, detect, translate):
    result = []
    for value in text.splitlines(keepends=True):
        if re.search(rf'[{HAN}]', value) and re.search('[A-Za-z]', value):
            pieces = (m.group() for m in SCRIPTS.finditer(value))
        else:
            pieces = [value]
        for piece in pieces:
            result.extend(translate_piece(chunk, detect, translate) for chunk in bounded(piece))
    return ''.join(result)


def translate_text(text, detect, translate):
    standalone = re.fullmatch(r'( {0,3})([a-z]+(?:_[a-z]+)+)([ \t]*(?:\r?\n)*)', text)
    if standalone:
        leading, words, trailing = standalone.groups()
        return leading + translate_prose(words.replace('_', ' '), detect, translate) + trailing
    output = []
    offset = 0
    for match in PROTECTED.finditer(text):
        output.append((translate_prose(text[offset:match.start()], detect, translate), False))
        output.append((match.group(), True))
        offset = match.end()
    output.append((translate_prose(text[offset:], detect, translate), False))
    result = []
    previous = ''
    previous_raw = False
    for value, raw in output:
        if not value:
            continue
        if previous and raw != previous_raw and not previous[-1].isspace() and not value[0].isspace():
            if (previous_raw and re.match(r'[A-Za-z0-9]', value)) or (
                raw and re.search(r'''[A-Za-z0-9][.!?,;:)"']*$''', previous)
            ):
                result.append(' ')
        result.append(value)
        previous, previous_raw = value, raw
    return ''.join(result)
