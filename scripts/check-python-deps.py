#!/usr/bin/env python3
"""Check whether the installed environment still satisfies this checkout."""
import importlib.metadata
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


def ready(root):
    try:
        import tomllib
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
        from packaging.utils import canonicalize_name

        project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
        distribution = importlib.metadata.distribution(project['name'])
        direct = json.loads(distribution.read_text('direct_url.json') or '{}')
        source = urlsplit(direct.get('url', ''))
        if (source.scheme != 'file' or source.netloc not in ('', 'localhost')
                or Path(unquote(source.path)).resolve() != root.resolve()
                or direct.get('dir_info', {}).get('editable') is not True
                or distribution.version != project['version']):
            return False
        python_requirement = SpecifierSet(project.get('requires-python', ''))
        if not python_requirement.contains('.'.join(map(str, sys.version_info[:3])), prereleases=True):
            return False

        for line in (root / 'requirements.lock').read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)', line)
            if not match or importlib.metadata.version(match.group(1)) != match.group(2):
                return False

        groups = [(project.get('dependencies', []), ''),
                  (project.get('optional-dependencies', {}).get('test', []), 'test')]
        installed_requirements = [Requirement(raw) for raw in distribution.requires or []]
        for dependencies, extra in groups:
            for raw in dependencies:
                requirement = Requirement(raw)
                if requirement.marker and not requirement.marker.evaluate({'extra': extra}):
                    continue
                if not any(
                    canonicalize_name(installed.name) == canonicalize_name(requirement.name)
                    and installed.specifier == requirement.specifier
                    and installed.extras == requirement.extras
                    and installed.url == requirement.url
                    and (installed.marker is None or installed.marker.evaluate({'extra': extra}))
                    for installed in installed_requirements
                ):
                    return False
                if requirement.url or not requirement.specifier.contains(
                        importlib.metadata.version(requirement.name), prereleases=True):
                    return False
        return True
    except (ImportError, ValueError, OSError, KeyError, TypeError, AttributeError,
            importlib.metadata.PackageNotFoundError):
        return False


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if ready(Path(sys.argv[1])) else 1)
