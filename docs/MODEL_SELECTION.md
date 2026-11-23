# 模型选择

| 模式 | 模型 | 适用场景 |
| --- | --- | --- |
| 速度优先 | Argos | 响应速度更重要 |
| 效果优先 | PLaMo 3 Translate 0.8B Q4_K_M | 更看重译文效果，模型加载和推理可能较慢 |

两者都在本机支持中英双向翻译，共用 OCR、语言识别和技术片段保护。效果取决于文本，重要译文需要核对。历史候选模型的试用记录见[模型调研](MODEL_RESEARCH.md)。

## 切换模型

```bash
ts --models
ts --model plamo 'Hello world.'
ts --check --model plamo
```

在交互终端运行 `ts --models`，用上下键选择、回车确认或 Esc 取消。`*` 标记已保存的选择，不可用的模式不能保存。非交互终端或 `--plain` 只显示列表。`--model` 只影响当前命令；没有保存设置时默认使用 Argos。模型缺失或配置错误时程序报错，不自动切换模型。

使用项目启动器且未设置 `XDG_CONFIG_HOME` 时，选择保存在 `.runtime/config/ts/config.json`；设置该变量时保存在其 `ts/config.json` 下。损坏的配置可先修复或移走；也可用 `--model argos` 临时绕过默认选择。

## 安装模型

`./install.sh` 联网安装 Argos 中英双向模型，以及 PLaMo 模型和 CPU 运行器。模型文件名、来源和 SHA256 记录在 `scripts/models.json` 和 `scripts/install-plamo.py`。

需要重新安装 PLaMo 时，可在项目目录运行：

```bash
./bin/python scripts/install-plamo.py
ts --check --model plamo
```

模型为 `plamo-3-translate-0.8b-Q4_K_M.gguf`，约 573 MB。添加 `--vulkan` 可安装可选的 Vulkan 运行器。脚本校验固定版本的 SHA256，不覆盖不同的现有文件。模型来源及许可见[第三方许可](THIRD_PARTY_LICENSES.md)。

模型默认位于 `.runtime/data/ts/models/plamo3/`。设置 `XDG_DATA_HOME` 时优先查找其 `ts/models/plamo3/`，找不到再查项目目录；`TS_PLAMO_MODEL` 可显式指定文件。`TS_PLAMO_RUNNER` 可指定本地 `llama-server`。默认优先尝试已安装的 Vulkan 运行器，启动失败时尝试 CPU；设置 `TS_PLAMO_DEVICE=cpu` 仅用 CPU。

本地模式每次翻译都启动 PLaMo 进程并在结束后关闭，语言识别也不会跨命令复用。可选 Docker 常驻模式会预热安装时选中的模型和语言识别器，其他模型或方向首次使用后也会保留；具体设备取决于容器能否访问显卡。模型和进程均不调用外部翻译服务。
