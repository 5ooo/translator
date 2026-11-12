# ts

ts 是一个 Linux 离线终端翻译工具。复制文字或截图后，输入 `ts`，即可自动识别并翻译剪贴板内容。

## 特点

- **剪贴板直接翻译**：复制文字或图片，无需粘贴到终端。
- **中英自动互译**：识别中文、英文和中英混合内容。
- **离线运行**：翻译在本机完成，内容无需上传。
- **模型可选**：支持 Argos 和 PLaMo。
- **适合技术文本**：尽量保留代码、路径、链接和常见技术缩写。
- **支持图片识别**：提取图片中的文字，并显示原文和译文。

## 使用

### 翻译剪贴板

复制一段文字，或复制一张包含文字的截图，然后在终端运行：

```bash
ts
```

文字和图片都可以直接识别。交互终端会显示原文和译文：

```text
原文：This is a test.
译文：这是一个测试。
```

### 输入文字

也可以在 `ts` 后直接输入文字：

```bash
ts 'Hello world.'
ts '这是一项测试。'
```

### 图片文件和管道

```bash
ts --image ./screenshot.png
printf 'Hello world.' | ts
```

### 切换模型

```bash
ts --models            # 查看模型
ts --set-model plamo   # 使用 PLaMo
ts --set-model argos   # 使用 Argos
```

## 安装

安装 uv 后，在项目目录运行：

```bash
./install.sh
```

首次安装通常需要联网，默认安装 Argos。PLaMo 需单独安装，详见[模型选择](docs/模型选择.md)。

## 更多文档

- [使用说明](docs/使用说明.md)
- [安装与配置](docs/安装与配置.md)
- [模型选择](docs/模型选择.md)
- [接口说明](docs/interface.md)
- [架构设计](docs/架构设计.md)
- [变更记录](CHANGELOG.md)
