# 第三方许可和模型来源

项目源码采用 [MIT 许可证](../LICENSE)。模型、运行器和依赖适用各自的许可证；本文列出主要来源，不是完整许可证审计，分发前需检查实际打包内容。

## Argos

项目使用 Argos Translate 1.9.6，其[程序许可证](https://raw.githubusercontent.com/argosopentech/argos-translate/v1.9.6/LICENSE)为 MIT。中英双向模型包的文件名、来源和 SHA256 记录在 `scripts/models.json`。

两个模型包的 README 说明，原始 OPUS 模型采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，并列出 Jörg Tiedemann 和 Santhosh Thottingal。CC BY 4.0 包含署名、许可链接和修改说明等要求。原始模型许可不等于模型包内所有文件的完整许可；分发前需进一步确认。

## PLaMo

项目使用 [PLaMo 3 Translate 0.8B Q4_K_M](https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF)，适用 PLaMo Community License。模型页说明个人及其他非商业使用免费，商业使用有注册或单独许可条件；以实际用途和许可文本为准。固定模型与运行器版本、来源及 SHA256 记录在 `scripts/install-plamo.py`。

## OCR

项目通过 [RapidOCR](https://github.com/RapidAI/RapidOCR) 运行 [PP-OCRv6](https://huggingface.co/collections/PaddlePaddle/pp-ocrv6)，项目与模型使用 Apache-2.0 许可，具体文件见各自的许可证与模型卡。Tiny 模型下载地址和 SHA256 记录在 `scripts/ocr-models.json`；Small 模型随 RapidOCR 包分发。

## 其他依赖

CTranslate2、SentencePiece、ONNX Runtime、llama.cpp、langid、Pillow、Rich、PyTorch 及传递依赖各有许可证。分发相关组件时，按实际内容检查并保留适用的许可和署名文件。
