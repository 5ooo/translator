# 终端显示设计

这次改动解决交互终端中的内容层次和等待反馈问题。翻译规则、OCR 文本、模型选择和非交互输出保持原有行为。

## 从三个原型中选择紧凑排版

设计探索比较了三个可运行的 Rich 原型。A 使用标题与留白，B 使用圆角卡片，C 使用原文与译文左右对照。浏览器检查深色、浅色和 40 列预览后，选择 A。它在窄屏中给正文保留更多空间，也便于选择和复制文字。B 的边框与留白占用更多终端空间，C 在窄屏中换行过多且出现省略。

根据后续使用反馈，最终布局以 `原文：内容` 和 `译文：内容` 显示结果。文字与图片都显示原文；图片原文来自同一次 OCR。原文标签与正文使用相同的淡色，译文正文沿用终端默认前景色。原文在终端中显示为多行时，译文之前增加一个空行。

内容通过 Rich `Text` 渲染，`[red]` 等字符不会解释成标记。长 URL、路径和中英文按终端宽度折行，不省略内容。文本内部换行保留，段落末尾的多余换行不额外显示；是否添加分隔空行按终端显示宽度判断。原型的等待时间和步骤是模拟，不能作为实际推理过程的证据。

## 只报告正在发生的步骤

`events.py` 定义 `Stage` 枚举与可选 `StageObserver` 回调。输入函数和引擎只报告步骤，不导入 Rich，也不写终端。`cli.py` 包装现有语言检测调用，因此 `text.py` 的分块、保护和翻译语义没有改变。

读取输入、剪贴板访问、图片识别、语言检测、首次载入某方向模型和每次推理之前各自触发事件。模型已有缓存时不报告模型载入。重复片段可以反复出现语言识别和翻译步骤。动画只表达等待，不用经过时间推算百分比。很快完成的阶段可能在下一帧刷新前被后续阶段替换，不人为延长等待。

主线程继续执行输入和推理。Rich 的刷新线程只绘制状态，不接管任务，不创建不能取消的后台推理任务。Presenter 在输出结果前停止动画，退出上下文时也停止动画，因此错误和 Ctrl-C 都先恢复光标，再交回既有错误处理逻辑。

## 保留非交互输出

只有 stdout 是终端、TERM 已设置且不是 dumb 或 unknown、没有设置 NO_COLOR、没有指定 `--plain` 时启用排版。动画还要求 stderr 是终端。stdin 是否连接终端只决定输入来源，不决定显示样式。

纯文本路径保留原有写入顺序。普通文字只输出译文，末尾缺少换行才补一个。图片输出依次为 `原文：`、原 OCR 文本、空行、`译文：` 和译文。保留 OCR 与译文已有的空白和末尾换行。成功的非交互调用不会向 stderr 写入状态文字。`--check` 和 `--install-model` 的输出沿用原格式。

## 参考成熟终端工具的具体做法

[Gum 的 spin 与 style](https://github.com/charmbracelet/gum) 提供紧凑状态和可控间距的参考。[uv 文档](https://docs.astral.sh/uv/) 中的步骤反馈支持采用简短的实际操作说明。这些资料用于交互设计参考，不用于速度或用户偏好结论。

[bat 的输出说明](https://github.com/sharkdp/bat) 与 [Command Line Interface Guidelines](https://clig.dev/#output) 支持保留可用于管道的纯文本输出，并按终端能力启用颜色。[Rich Console](https://rich.readthedocs.io/en/stable/console.html) 提供终端能力检测、字面文本和宽度处理。[Rich Live](https://rich.readthedocs.io/en/stable/live.html) 提供完成后清除状态的 transient 显示。

Experience First 让布局保留正常字重正文与可复制内容。Exhaust the Design Space 让三种实际原型的比较发生在应用修改之前。

## 设计原则与实际效果

Experience First 选择可复制的正文和清晰的原译文层次。Exhaust the Design Space 通过三种原型比较排除卡片与左右对照。Foundational Thinking 与 Model the Domain 将状态建模为少量真实阶段，避免用计时器推算百分比。Laziness Protocol 保留一次性命令和一个显示边界，不增加全屏界面。Test Behavior, Not Implementation 验证输出字节、折行和退出行为；Prove It Works 使用已安装命令的真实终端及剪贴板验收。

[旧版截图](assets/terminal-preview.png)和[旧版动画重放](assets/terminal-preview.gif)保留为设计记录，不代表当前两行布局。应用沿用终端背景和默认正文色。
