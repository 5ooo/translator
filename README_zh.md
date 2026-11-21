([English](README.md) | 简体中文)

# **T**ran**s**lator

ts 是一个 Linux 离线终端中英翻译工具。复制文字或截图后运行 `ts`，即可识别并翻译剪贴板内容。

## 特点

- 直接翻译剪贴板文字和图片，无需粘贴到终端。
- 安装完成后离线翻译中文、英文及中英混合内容。
- 速度优先选择 Argos，效果优先选择 PLaMo。
- 图片显示 OCR 原文和译文；代码、路径、链接和常见技术缩写会尽量保留。

## 使用

复制文字或图片后运行：

```bash
ts
```

也可以输入文字、图片路径或管道内容：

```bash
ts 'Hello world.'
ts --image ./screenshot.png
printf 'Hello world.' | ts
```

在支持排版的交互终端中，结果显示原文和译文。运行 `ts --models` 可选择默认模型：上下键移动，回车确认，Esc 取消，`*` 表示当前选择。

## 安装

收到离线包后，解压并在目录内运行：

```bash
./install.sh --offline
export PATH="$HOME/.local/bin:$PATH"
```

离线包包含两个模型和运行依赖，无需联网或安装 uv。构建和测试平台为 Ubuntu 24.04 x86-64，其他系统尚未验证。

从源码安装时，在项目目录运行 `./install.sh`。首次安装需要联网，脚本会准备 uv、依赖和两个模型；安装完成后可离线使用。如果找不到 `ts` 命令，运行 `export PATH="$HOME/.local/bin:$PATH"`。详见[安装与配置](docs/INSTALLATION.md)和[模型选择](docs/MODEL_SELECTION.md)。

## 文档

[使用说明](docs/USAGE.md) · [命令参考](docs/INTERFACE.md) · [架构设计](docs/ARCHITECTURE.md) · [测试报告](docs/TEST_REPORT.md) · [第三方许可](docs/THIRD_PARTY_LICENSES.md) · [变更记录](CHANGELOG.md)
