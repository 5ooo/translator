# 安装与配置

## 在线安装

在 Linux x86-64 系统中，克隆项目并运行安装脚本：

```bash
git clone https://github.com/5ooo/translator.git
cd translator
./install.sh
export PATH="$HOME/.local/bin:$PATH"
ts --check
```

首次安装需要联网。脚本会准备 Python、依赖、OCR、剪贴板工具和两个翻译模型；安装完成后，语言识别、OCR 和翻译都在本地运行，不需要联网。`export` 只影响当前 shell；需要时将 PATH 设置加入自己的 shell 配置。

脚本复用项目内或系统中已有的 uv 0.9.10；否则使用 curl 或 wget 下载固定版本的[官方 uv 安装脚本](https://docs.astral.sh/uv/reference/installer/)，校验 SHA256 后安装到 `.runtime/tools/uv-0.9.10/`，不修改 shell 配置。脚本默认在 `.runtime/python/` 安装 Python 3.12.12，在 `.venv-uv/` 安装锁定依赖，并下载和校验两个模型及 PLaMo CPU 运行器。

运行 `./scripts/check_env.sh` 可在安装前检查环境。首次安装需要访问 uv、Python、依赖包和模型的下载地址；下载失败时检查网络后重新运行 `./install.sh`。已安装且校验通过的资源会复用。

如果系统缺少 Tesseract、语言包或剪贴板工具，脚本尝试使用 `apt-get` 和 `dpkg-deb` 下载并解包到 `.runtime/system/`，不使用 sudo。非 Debian 系统需自行准备这些工具。Linux 共享库、桌面显示服务和显卡驱动由系统提供。

当前安装流程在 Ubuntu 24.04 x86-64、Python 3.12 上验证；其他系统尚未验证。剪贴板功能需要 X11 或 Wayland 桌面会话，PLaMo 需要本机回环接口和可读的 `/proc`。首次创建环境时可用 `TS_PYTHON` 指定解释器；已有虚拟环境不会自动更换，外部解释器创建的环境不保证可随目录移动。

安装脚本创建 `~/.local/bin/ts` 链接。若同名文件或链接属于其他命令，脚本不会覆盖，可直接运行 `./bin/ts`。移动项目后，确认旧链接属于本项目，再更新链接。

## 本地文件

| 路径 | 内容 |
| --- | --- |
| `.runtime/python/`、`.venv-uv/` | 项目内 Python 和依赖 |
| `.runtime/data/`、`.runtime/tools/` | 模型、PLaMo 运行器和自动安装的 uv |
| `.runtime/system/` | 项目内 OCR 与剪贴板工具 |
| `.runtime/config/`、`.runtime/downloads/` | 模型设置和模型下载缓存 |

这些本机文件不随 Git 源码提交。`bin/ts` 默认使用项目内目录；`XDG_DATA_HOME`、`XDG_CONFIG_HOME`、`XDG_CACHE_HOME`、`ARGOS_PACKAGES_DIR` 和 `TESSDATA_PREFIX` 可覆盖相应设置。`XDG_CONFIG_HOME` 须为绝对路径。

## 故障排查

- 运行 `ts --check` 或 `ts --check --model plamo` 检查模型与依赖。剪贴板工具缺失只会显示提示，需在相应桌面环境中补齐。
- 无参数命令未读取剪贴板时，检查当前终端是否属于 X11 或 Wayland 会话。运行 `type -t ts` 检查是否有同名 shell 函数遮蔽程序；确认后可使用 `unset -f ts`，或直接运行项目的 `bin/ts`。
- 按 `Ctrl+C` 可中断当前命令。PLaMo 运行器随命令退出，无需手动停止。

测试范围见[测试报告](TEST_REPORT.md)，模型来源和分发许可见[第三方许可](THIRD_PARTY_LICENSES.md)。
