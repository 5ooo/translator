([简体中文](README_zh.md) | English)

# **T**ran**s**lator

`ts` is an offline Chinese-English terminal translator for Linux. Copy text or an image, then run `ts` to translate the clipboard.

## Features

- Translate clipboard text and images without pasting into the terminal.
- Translate Chinese, English, and mixed text locally after setup.
- Choose Argos for speed or PLaMo for translation quality.
- Show the OCR text and translation for images. Preserve code, paths, URLs, and common technical abbreviations where possible.

## Usage

Copy text or an image, then run:

```bash
ts
```

You can also pass text, an image path, or standard input:

```bash
ts 'Hello world.'
ts --image ./screenshot.png
printf 'Hello world.' | ts
```

In a supported interactive terminal, the result shows the original and the translation. The interface is currently in Chinese: `原文` means original and `译文` means translation.

Select the default model with `ts --models`. Use the arrow keys, Enter to confirm, and Esc to cancel. `速度优先` is Argos, `效果优先` is PLaMo, and `*` marks the current choice.

## Installation

For an offline bundle, extract it and run these commands in the extracted directory:

```bash
./install.sh --offline
export PATH="$HOME/.local/bin:$PATH"
```

The bundle includes both models and their runtime dependencies. It was built and tested on Ubuntu 24.04 x86-64. Other systems have not been verified.

To install from source, run `./install.sh` in the project directory. The first installation requires a network connection and prepares uv, dependencies, and both models. You can use the tool offline afterward. If the shell cannot find `ts`, run `export PATH="$HOME/.local/bin:$PATH"`. See [installation](docs/INSTALLATION.md) and [model selection](docs/MODEL_SELECTION.md).

## Documentation

Detailed guides are in Chinese: [usage](docs/USAGE.md), [command reference](docs/INTERFACE.md), [architecture](docs/ARCHITECTURE.md), [tests](docs/TEST_REPORT.md), [third-party licenses](docs/THIRD_PARTY_LICENSES.md), and the [changelog](CHANGELOG.md).
