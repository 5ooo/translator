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

if command -v uv >/dev/null 2>&1; then
    printf 'uv：可用\n'
else
    printf 'uv：未找到，请先安装 uv。\n' >&2
    exit 1
fi

export PATH="$project_dir/.runtime/system/usr/bin:$PATH"
export LD_LIBRARY_PATH="$project_dir/.runtime/system/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [[ -d "$project_dir/.runtime/system/usr/share/tesseract-ocr/5/tessdata" ]]; then
    export TESSDATA_PREFIX="${TESSDATA_PREFIX:-$project_dir/.runtime/system/usr/share/tesseract-ocr/5/tessdata}"
fi
missing_native=false
for tool in tesseract wl-paste xclip; do
    if command -v "$tool" >/dev/null 2>&1; then
        printf '%s：可用\n' "$tool"
    else
        printf '%s：未找到\n' "$tool"
        missing_native=true
    fi
done
if command -v tesseract >/dev/null 2>&1; then
    if langs="$(tesseract --list-langs 2>/dev/null)" && \
       [[ " $langs " =~ (^|[[:space:]])eng($|[[:space:]]) ]] && \
       [[ " $langs " =~ (^|[[:space:]])chi_sim($|[[:space:]]) ]]; then
        printf 'Tesseract eng+chi_sim：可用\n'
    else
        printf 'Tesseract eng+chi_sim：未找到或不可用\n'
        missing_native=true
    fi
fi
if [[ "$missing_native" == true ]]; then
    if command -v apt-get >/dev/null 2>&1 && command -v dpkg-deb >/dev/null 2>&1; then
        printf '安装脚本可尝试下载缺失的系统工具和语言包。\n'
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
