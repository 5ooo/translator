#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if (( $# )); then
    printf '用法：%s\n' "$0" >&2
    exit 2
fi

system="$(uname -s)"
architecture="$(uname -m)"
printf '系统：%s %s\n' "$system" "$architecture"
if [[ "$system" != Linux ]]; then
    printf '当前安装流程仅验证 Linux。\n' >&2
    exit 1
fi
if [[ "$architecture" != x86_64 && "$architecture" != amd64 ]]; then
    printf '提示：PLaMo 运行器自动安装仅支持 Linux x86-64。\n'
fi

local_uv="$project_dir/.runtime/tools/uv-0.9.10/uv"
if [[ -x "$local_uv" ]]; then
    if [[ "$("$local_uv" --version)" != 'uv 0.9.10' ]]; then
        printf '项目内 uv 版本不符：%s\n' "$local_uv" >&2
        exit 1
    fi
    printf 'uv 0.9.10：可用\n'
elif command -v uv >/dev/null 2>&1 && [[ "$(uv --version)" == 'uv 0.9.10' ]]; then
    printf 'uv 0.9.10：可用\n'
elif [[ -e "$local_uv" || -L "$local_uv" || -e "${local_uv%/*}/uvx" || -L "${local_uv%/*}/uvx" ]]; then
    printf '项目内 uv 文件已存在但不可用：%s\n' "${local_uv%/*}" >&2
    exit 1
elif command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then
    printf 'uv 0.9.10：安装时将下载到项目目录\n'
else
    printf '缺少 uv 0.9.10、curl 和 wget，无法自动部署。\n' >&2
    exit 1
fi

export PATH="$project_dir/.runtime/system/usr/bin:$PATH"
export LD_LIBRARY_PATH="$project_dir/.runtime/system/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
missing_native=false
for tool in wl-paste xclip; do
    if command -v "$tool" >/dev/null 2>&1; then
        printf '%s：可用\n' "$tool"
    else
        printf '%s：未找到\n' "$tool"
        missing_native=true
    fi
done
if [[ "$missing_native" == true ]]; then
    if command -v apt-get >/dev/null 2>&1 && command -v dpkg-deb >/dev/null 2>&1; then
        printf '安装脚本可尝试下载缺失的剪贴板工具。\n'
    else
        printf '缺少系统工具，且无法使用 apt-get/dpkg-deb 自动安装。\n' >&2
        exit 1
    fi
fi

if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    printf '桌面显示会话：已设置\n'
else
    printf '桌面显示会话：未设置；可使用显式文字或管道。\n'
fi
if [[ -x "$project_dir/.venv-uv/bin/python" ]]; then
    printf '项目 Python 环境：已存在\n'
else
    printf '项目 Python 环境：待安装\n'
fi
printf '项目所在磁盘：\n'
df -h -- "$project_dir"
printf '部署前检查完成。实际模型可用性请在安装后运行 ts --check。\n'
