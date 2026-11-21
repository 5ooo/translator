# 安装与配置

## 安装离线包

将离线包复制到目标机器，解压后运行：

```bash
tar -xzf ts-offline-linux-x86_64.tar.gz
cd ts
./install.sh --offline
export PATH="$HOME/.local/bin:$PATH"
ts --check
ts --check --model plamo
```

离线安装检查两个模型和公共依赖，并创建 `~/.local/bin/ts` 链接，无需网络或 uv。`export` 只影响当前 shell；需要时将该 PATH 设置加入自己的 shell 配置。若同名文件或链接属于其他命令，安装脚本不会覆盖，可直接运行 `./bin/ts`。

离线包包含项目内 Python、两个模型、PLaMo CPU 运行器、OCR、剪贴板工具及所需的非 glibc 共享库。它在 Ubuntu 24.04 x86-64 上构建和测试；其他发行版、CPU 架构和较旧 glibc 尚未验证。系统仍需提供兼容的 glibc；剪贴板需要 X11 或 Wayland 桌面会话，PLaMo 需要本机回环接口和可读的 `/proc`。Vulkan 显卡运行器仅在打包时已安装才包含在内。

请保留解压后的项目目录。移动目录后，确认旧链接属于本项目，再更新 `~/.local/bin/ts`；安装脚本不会覆盖指向其他位置的旧链接。

## 从源码安装

首次安装需要联网。在项目目录运行：

```bash
./install.sh
```

脚本复用项目内或系统中已有的 uv 0.9.10；否则使用 curl 或 wget 下载固定版本的[官方 uv 安装脚本](https://docs.astral.sh/uv/reference/installer/)，校验 SHA256 后安装到 `.runtime/tools/uv-0.9.10/`，不修改 shell 配置。它默认在 `.runtime/python/` 安装 Python 3.12.12，在 `.venv-uv/` 安装锁定依赖，并下载和校验 Argos 双向模型、PLaMo 模型及 CPU 运行器。安装完成后翻译不需要联网。

运行 `./scripts/check_env.sh` 可在安装前检查环境。首次安装需要访问 uv、Python、依赖包和模型的下载地址；下载失败时检查网络后重新运行 `./install.sh`。

如果系统缺少 Tesseract、语言包或剪贴板工具，脚本尝试使用 `apt-get` 和 `dpkg-deb` 下载并解包到 `.runtime/system/`，不使用 sudo。非 Debian 系统需自行准备这些工具。Linux 共享库、桌面显示服务和显卡驱动由系统提供。

首次创建环境时可用 `TS_PYTHON` 指定解释器；已有虚拟环境不会自动更换。锁定依赖在 Python 3.12 上验收，建议使用默认版本。外部解释器创建的环境不保证可随目录移动。

## 本地文件和离线包构建

| 路径 | 内容 |
| --- | --- |
| `.runtime/python/`、`.venv-uv/` | 项目内 Python 和依赖 |
| `.runtime/data/`、`.runtime/tools/` | 模型、PLaMo 运行器和自动安装的 uv |
| `.runtime/system/` | 项目内 OCR 与剪贴板工具 |
| `.runtime/config/`、`.runtime/downloads/` | 模型设置和模型下载缓存 |

这些本机文件不随 Git 源码提交。`bin/ts` 默认使用项目内目录，`XDG_DATA_HOME`、`XDG_CONFIG_HOME`、`XDG_CACHE_HOME`、`ARGOS_PACKAGES_DIR` 和 `TESSDATA_PREFIX` 可覆盖相应设置。`XDG_CONFIG_HOME` 须为绝对路径。

准备好项目内 Python、Argos 双向模型、PLaMo 模型与 CPU 运行器、Tesseract 及中英文语言包、`xclip` 和 `wl-paste` 后，可构建离线包：

```bash
./bin/python scripts/package-offline.py --output ./dist/ts-offline-new.tar.gz
```

打包脚本要求这些 OCR 和剪贴板工具位于项目 `.runtime/system/`，仅依赖系统中的工具不足以打包。它不会覆盖已有输出文件，也不打包本机配置和缓存。

## 故障排查

- 运行 `ts --check` 或 `ts --check --model plamo` 检查模型与依赖。剪贴板工具缺失只会显示提示，需在相应桌面环境中补齐。
- 无参数命令未读取剪贴板时，检查当前终端是否属于 X11 或 Wayland 会话。运行 `type -t ts` 检查是否有同名 shell 函数遮蔽程序；确认后可使用 `unset -f ts`，或直接运行项目的 `bin/ts`。
- 按 `Ctrl+C` 可中断当前命令。PLaMo 运行器随命令退出，无需手动停止。

测试范围见[测试报告](TEST_REPORT.md)，模型来源和分发许可见[第三方许可](THIRD_PARTY_LICENSES.md)。
