# 安装与配置

## 在线安装

在 Linux x86-64 系统中，克隆项目并运行安装脚本：

```bash
git clone https://github.com/5ooo/translator.git
cd translator
./install.sh
ts --check
```

首次安装需要联网。脚本会准备 Python、依赖、OCR、剪贴板工具和两个翻译模型；安装完成后，语言识别、OCR 和翻译都在本地运行，不需要联网。

脚本复用项目内或系统中已有的 uv 0.9.10；否则使用 curl 或 wget 下载固定版本的[官方 uv 安装脚本](https://docs.astral.sh/uv/reference/installer/)，校验 SHA256 后安装到 `.runtime/tools/uv-0.9.10/`，不修改 shell 配置。脚本默认在 `.runtime/python/` 安装 Python 3.12.12，在 `.venv-uv/` 安装锁定依赖，并下载和校验两个模型及 PLaMo CPU 运行器。

重新安装时，如果 Python 环境与锁定依赖和当前项目一致，脚本会直接复用，不再访问 Python 包索引；依赖缺失或版本变化时才调用 uv 安装。Docker 镜像首次构建仍需联网。

运行 `./scripts/check_env.sh` 可在安装前检查环境。首次安装需要访问 uv、Python、依赖包和模型的下载地址；下载失败时检查网络后重新运行 `./install.sh`。已安装且校验通过的资源会复用。

如果系统缺少 Tesseract、语言包或剪贴板工具，脚本尝试使用 `apt-get` 和 `dpkg-deb` 下载并解包到 `.runtime/system/`，不使用 sudo。非 Debian 系统需自行准备这些工具。Linux 共享库、桌面显示服务和显卡驱动由系统提供。

当前安装流程在 Ubuntu 24.04 x86-64、Python 3.12 上验证；其他系统尚未验证。剪贴板功能需要 X11 或 Wayland 桌面会话，PLaMo 需要本机回环接口和可读的 `/proc`。首次创建环境时可用 `TS_PYTHON` 指定解释器；已有虚拟环境不会自动更换，外部解释器创建的环境不保证可随目录移动。

安装脚本优先在 PATH 中的 `~/.local/bin` 或 `~/bin` 创建 `ts` 链接；如果没有可用的用户目录，则使用 PATH 中的 `/usr/local/bin`。写入该系统目录需要管理员权限，安装时可能要求输入 `sudo` 密码。若已有同名命令，脚本不会覆盖；可直接运行 `./bin/ts`。如果这些目录均不在 PATH 中，脚本会提示无法安装命令。移动项目后，确认旧链接属于本项目，再更新链接。

## 可选：Docker 常驻模式

先安装并启动 Docker，确保当前用户无需提权即可访问 Docker 服务，然后在项目目录运行：

```bash
./install.sh --docker
```

安装时联网构建精简镜像，并只读挂载已经安装的 Python 依赖、模型和运行器，不在镜像中复制模型。容器预热当前选中的模型和语言识别器，后续 `ts` 命令保持原有用法。切换到另一模型或 Argos 的另一翻译方向时，首次使用仍需加载；加载后会保留到容器退出。常驻服务会持续占用内存，使用显卡时也会占用显存。

剪贴板、图片 OCR 和输出仍由宿主机处理。容器使用私有 Unix socket 和 `--network none`，运行时不访问外网。Docker 服务重启后，容器按 `unless-stopped` 策略启动并重新预热；如果手动停止容器，可通过安装时显示的名称运行 `docker start`，或重新运行 `./install.sh --docker`。

容器需要与项目环境匹配的 Python 3.12。已安装 Vulkan 运行器且主机检测到 NVIDIA 显卡时，安装器会尝试配置 NVIDIA 容器；无法启用时提示并回退 CPU。NVIDIA GPU 容器支持需预先配置宿主驱动和 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)，Vulkan 需要 `graphics` 驱动能力。CPU 模式与宿主显卡模式的速度可能不同；也可在安装前设置 `TS_PLAMO_DEVICE=cpu` 强制使用 CPU。

如需排查显卡未启用的原因，可运行 `TS_DOCKER_DEBUG=1 ./install.sh --docker` 查看详细信息。

如尚未安装 Vulkan 运行器，可联网运行 `./bin/python scripts/install-plamo.py --vulkan`，再运行 `./install.sh --docker`。安装器会通过实际翻译和显存占用检查确认 NVIDIA 容器是否在使用显卡；检查失败时回退 CPU。

模型目录、运行器或项目源码发生变化，或项目移动后，请在对应环境变量下重新运行 `./install.sh --docker`。当前容器复用宿主安装时的路径；`XDG_DATA_HOME`、`ARGOS_PACKAGES_DIR`、`TS_PLAMO_MODEL`、`TS_PLAMO_RUNNER` 或 `TS_PLAMO_DEVICE` 的设置变化后也需重建。要切回普通本地模式并停止本项目的常驻容器：

```bash
./install.sh --local
```

切回本地模式需要 Docker 可访问，以便先停止并清理本项目的容器；如果 Docker 不可用，配置会保留，恢复后重新运行该命令。安装器不会覆盖其他容器；服务验证成功后才切换配置。Docker 不可用或服务失联时会提示错误，不会悄悄切换模型。

## 本地文件

| 路径 | 内容 |
| --- | --- |
| `.runtime/python/`、`.venv-uv/` | 项目内 Python 和依赖 |
| `.runtime/data/`、`.runtime/tools/` | 模型、PLaMo 运行器和自动安装的 uv |
| `.runtime/system/` | 项目内 OCR 与剪贴板工具 |
| `.runtime/config/`、`.runtime/downloads/` | 模型设置和模型下载缓存 |
| `.runtime/docker/` | 可选常驻服务的私有 socket 和安装锁 |

这些本机文件不随 Git 源码提交。`bin/ts` 默认使用项目内目录；`XDG_DATA_HOME`、`XDG_CONFIG_HOME`、`XDG_CACHE_HOME`、`ARGOS_PACKAGES_DIR` 和 `TESSDATA_PREFIX` 可覆盖相应设置。`XDG_CONFIG_HOME` 须为绝对路径。

## 故障排查

- 运行 `ts --check` 或 `ts --check --model plamo` 检查模型与依赖。剪贴板工具缺失只会显示提示，需在相应桌面环境中补齐。
- 无参数命令未读取剪贴板时，检查当前终端是否属于 X11 或 Wayland 会话。运行 `type -t ts` 检查是否有同名 shell 函数遮蔽程序；确认后可使用 `unset -f ts`，或直接运行项目的 `bin/ts`。
- 按 `Ctrl+C` 可中断当前命令。本地模式的 PLaMo 运行器随命令退出；Docker 模式的服务继续运行，可用 `./install.sh --local` 停止。

测试范围见[测试报告](TEST_REPORT.md)，模型来源和分发许可见[第三方许可](THIRD_PARTY_LICENSES.md)。
