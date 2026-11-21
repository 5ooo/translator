# 本机翻译模型调研记录

本记录保留 2026-11-10 的候选模型试用；当前工具只支持 Argos 和 PLaMo，安装方式见[模型选择](MODEL_SELECTION.md)。当时的目标是本机中英翻译及较小的模型体积。PLaMo 不在下列小样本对照中，当前采用的 Q4_K_M 文件约 573 MB。

| 当时试用或调研的候选 | 当时记录的模型大小 | 结果 |
| --- | --- | --- |
| Argos | 中英双向合计约 172 MB | 本机基线，已运行 |
| [M2M100-418M](https://huggingface.co/gn64/M2M100_418M_CTranslate2) | INT8 约 496 MB | 第三方 CTranslate2 转换，已运行中英双向 |
| [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) | 量化文件约 523 MB | 使用 Ollama 试跑，结果受提示词影响 |
| [Haidass-Translate-143M](https://huggingface.co/DALabCommunity/Haidass-Translate-143M) | Q8 约 188 MB | 试跑时出现短语未译和句子误译 |
| [Hy-MT2-1.8B](https://huggingface.co/tencent/Hy-MT2-1.8B) | Q4 约 1.13 GB；1.25-bit 约 440 MB | 未接入；1.25-bit 版本依赖专用内核，未验证本机兼容性 |

当时在 CPU 上用少量自拟文本比较，模型的提示词和运行方式不同，不能作为统一基准或质量排名。例如 `grab box` 分别得到 Argos“抓图框”、M2M100“抓盒子”、Qwen“获取盒子”和 Haidass“Grab Box”。模型大小不包含推理程序及内存开销。
