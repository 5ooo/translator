# 模型选择

| 模式 | 文字翻译 | 图片识别 | 适用场景 |
| --- | --- | --- | --- |
| 速度优先 | Argos | PP-OCRv6 Tiny | 响应速度更重要 |
| 效果优先 | PLaMo 3 Translate 0.8B Q4_K_M | PP-OCRv6 Small | 更看重识别和翻译效果，模型加载和推理可能较慢 |

两者都在本机支持中英双向翻译，共用语言识别和技术片段保护。选择模式会同时切换 OCR 和翻译模型。效果取决于输入，重要译文需要核对。候选模型的试用记录见[翻译模型调研](MODEL_RESEARCH.md)和 [OCR 对比测试](OCR_RESEARCH.md)。

## 切换模型

```bash
ts --models
ts --model plamo 'Hello world.'
ts --check --model plamo
```

在交互终端运行 `ts --models`，用上下键选择、回车确认或 Esc 取消。`*` 标记已保存的选择；OCR 或翻译模型缺失时，该模式不能保存。非交互终端或 `--plain` 只显示列表。`--model` 同时指定本次 OCR 和翻译模型，没有保存设置时默认使用速度优先。模型缺失或配置错误时程序报错，不自动切换模型。

使用项目启动器且未设置 `XDG_CONFIG_HOME` 时，选择保存在 `.runtime/config/ts/config.json`；设置该变量时保存在其 `ts/config.json` 下。损坏的配置可先修复或移走；也可用 `--model argos` 临时绕过默认选择。

## 安装模型

`./install.sh` 联网安装 Argos 中英双向模型、PLaMo 模型和 CPU 运行器，以及 PP-OCRv6 Tiny 和 Small。Tiny 模型下载来源和 SHA256 记录在 `scripts/ocr-models.json`；Small 随固定版本的 RapidOCR Python 包安装。翻译模型来源和 SHA256 记录在 `scripts/models.json` 和 `scripts/install-plamo.py`。

需要重新安装 PLaMo 时，可在项目目录运行：

```bash
./bin/python scripts/install-plamo.py
ts --check --model plamo
```

模型为 `plamo-3-translate-0.8b-Q4_K_M.gguf`，约 573 MB。添加 `--vulkan` 可安装可选的 Vulkan 运行器。脚本校验固定版本的 SHA256，不覆盖不同的现有文件。模型来源及许可见[第三方许可](THIRD_PARTY_LICENSES.md)。

模型默认位于 `.runtime/data/ts/models/plamo3/`。设置 `XDG_DATA_HOME` 时优先查找其 `ts/models/plamo3/`，找不到再查项目目录；`TS_PLAMO_MODEL` 可显式指定文件。`TS_PLAMO_RUNNER` 可指定本地 `llama-server`。默认优先尝试已安装的 Vulkan 运行器，启动失败时尝试 CPU；设置 `TS_PLAMO_DEVICE=cpu` 仅用 CPU。

本地模式每次图片翻译都会加载 OCR，每次翻译也会重新加载语言识别器和所选翻译模型；PLaMo 进程在命令结束后关闭。可选 Docker 常驻模式会预热安装时选中的 OCR、翻译模型和语言识别器，其他模型或方向首次使用后也会保留；具体设备取决于容器能否访问显卡。模型和进程均不调用外部翻译服务。

Tiny 检测和识别模型位于 `.runtime/data/ts/models/ocr/`；Small 模型随 `.venv-uv/` 的 RapidOCR 安装。Docker 将这两处模型只读挂载到容器中。设置 `XDG_DATA_HOME` 时，Tiny 会先查找其中的 `ts/models/ocr/`，没有完整模型时回退到项目目录。
