#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--docker' && "$1" != '--local' ) ]]; then
    printf '用法：%s [--docker|--local]\n' "$0" >&2
    exit 2
fi
mode="${1:-}"
if [[ "$mode" == '--local' ]]; then
    if [[ ! -x "$project_dir/.venv-uv/bin/python" ]]; then
        printf '请先运行 ./install.sh 安装本地环境。\n' >&2
        exit 1
    fi
    "$project_dir/bin/python" "$project_dir/scripts/install-docker.py" disable
    exit 0
fi
if [[ "$mode" == '--docker' ]]; then
    if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
        printf 'Docker 不可用：请先安装并启动 Docker，确保当前用户有访问权限。\n' >&2
        exit 1
    fi
fi
if [[ -x "$project_dir/.venv-uv/bin/python" ]] && \
   env -u PYTHONHOME -u PYTHONPATH PYTHONNOUSERSITE=1 \
       "$project_dir/.venv-uv/bin/python" "$project_dir/scripts/check-python-deps.py" "$project_dir"; then
    printf 'Python 环境与锁定依赖已满足，直接复用。\n'
else
    uv_dir="$project_dir/.runtime/tools/uv-0.9.10"
    uv_cmd="$uv_dir/uv"
    if [[ -x "$uv_cmd" ]]; then
        if [[ "$("$uv_cmd" --version)" != 'uv 0.9.10' ]]; then
            printf '项目内 uv 版本不符，请检查 %s。\n' "$uv_cmd" >&2
            exit 1
        fi
    elif command -v uv >/dev/null 2>&1 && [[ "$(uv --version)" == 'uv 0.9.10' ]]; then
        uv_cmd="$(command -v uv)"
    else
        if [[ -e "$uv_cmd" || -L "$uv_cmd" || -e "$uv_dir/uvx" || -L "$uv_dir/uvx" ]]; then
            printf '项目内 uv 文件已存在但不可用，未覆盖：%s\n' "$uv_dir" >&2
            exit 1
        fi
        installer="$(mktemp "${TMPDIR:-/tmp}/ts-uv-installer.XXXXXXXX")"
        trap 'rm -f -- "$installer"' EXIT
        installer_url='https://astral.sh/uv/0.9.10/install.sh'
        printf '安装项目内 uv 0.9.10。\n'
        if command -v curl >/dev/null 2>&1 && \
           curl --fail --location --silent --show-error --connect-timeout 15 --max-time 120 --retry 2 "$installer_url" --output "$installer"; then
            :
        elif command -v wget >/dev/null 2>&1 && \
             wget --quiet --timeout=120 --tries=3 --output-document="$installer" "$installer_url"; then
            :
        else
            printf '无法下载 uv 安装脚本，请检查网络及 curl 或 wget。\n' >&2
            exit 1
        fi
        checksum="$(sha256sum "$installer")"
        if [[ "${checksum%% *}" != '578d164a618b6b2825017d6dab73b00925e3895b47f22b25434b3fee2ec9f849' ]]; then
            printf 'uv 安装脚本 SHA256 校验失败。\n' >&2
            exit 1
        fi
        mkdir -p "$uv_dir"
        env -u UV_INSTALL_DIR -u CARGO_DIST_FORCE_INSTALL_DIR \
            UV_UNMANAGED_INSTALL="$uv_dir" UV_NO_MODIFY_PATH=1 sh "$installer"
        if [[ ! -x "$uv_cmd" || "$("$uv_cmd" --version)" != 'uv 0.9.10' ]]; then
            printf '项目内 uv 安装失败。\n' >&2
            exit 1
        fi
        rm -f -- "$installer"
        trap - EXIT
    fi
    if [[ ! -x "$project_dir/.venv-uv/bin/python" ]]; then
        if [[ -n "${TS_PYTHON:-}" ]]; then
            python_path="$TS_PYTHON"
        else
            python_dir="$project_dir/.runtime/python"
            UV_PYTHON_INSTALL_DIR="$python_dir" "$uv_cmd" python install --no-bin 3.12.12
            python_path="$(UV_PYTHON_INSTALL_DIR="$python_dir" "$uv_cmd" python find --managed-python --no-python-downloads 3.12.12)"
            case "$(readlink -f -- "$python_path")" in
                "$(readlink -f -- "$python_dir")"/*) ;;
                *) printf '未找到项目内的 Python 解释器。\n' >&2; exit 1 ;;
            esac
        fi
        "$uv_cmd" venv --python "$python_path" "$project_dir/.venv-uv"
    fi
    "$uv_cmd" pip install --python "$project_dir/.venv-uv/bin/python" --torch-backend cpu --link-mode copy --constraint "$project_dir/requirements.lock" -e "$project_dir[test]"
fi
"$project_dir/.venv-uv/bin/python" "$project_dir/scripts/provision.py"
"$project_dir/bin/python" "$project_dir/scripts/install-plamo.py"
TS_INSTALL_CHECK=1 "$project_dir/bin/ts" --check --model argos
TS_INSTALL_CHECK=1 "$project_dir/bin/ts" --check --model plamo
if [[ "$mode" == '--docker' ]]; then
    "$project_dir/bin/python" "$project_dir/scripts/install-docker.py" install
fi
printf '\n安装完成，无需激活 Python 环境，可直接运行 ts。\n'
