#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -gt 0 ]]; then
    if [[ $# -ne 1 || "$1" != '--offline' ]]; then
        printf '用法：%s [--offline]\n' "$0" >&2
        exit 2
    fi
    "$project_dir/bin/ts" --check --model argos
    "$project_dir/bin/ts" --check --model plamo
    "$project_dir/bin/python" "$project_dir/scripts/provision.py" --link-only
    printf '\n离线安装完成。\n'
    exit 0
fi
if ! command -v uv >/dev/null 2>&1; then
    printf '缺少 uv，请先安装 uv 后重试。\n' >&2
    exit 1
fi
if [[ ! -x "$project_dir/.venv-uv/bin/python" ]]; then
    if [[ -n "${TS_PYTHON:-}" ]]; then
        python_path="$TS_PYTHON"
    else
        python_dir="$project_dir/.runtime/python"
        UV_PYTHON_INSTALL_DIR="$python_dir" uv python install --no-bin 3.12.12
        python_path="$(UV_PYTHON_INSTALL_DIR="$python_dir" uv python find --managed-python --no-python-downloads 3.12.12)"
        case "$(readlink -f -- "$python_path")" in
            "$(readlink -f -- "$python_dir")"/*) ;;
            *) printf '未找到项目内的 Python 解释器。\n' >&2; exit 1 ;;
        esac
    fi
    uv venv --python "$python_path" "$project_dir/.venv-uv"
fi
uv pip install --python "$project_dir/.venv-uv/bin/python" --torch-backend cpu --link-mode copy --constraint "$project_dir/requirements.lock" -e "$project_dir[test]"
"$project_dir/.venv-uv/bin/python" "$project_dir/scripts/provision.py"
"$project_dir/bin/ts" --check
printf '\n安装完成，新终端可直接使用 ts，无需激活 Python 环境。\n'
