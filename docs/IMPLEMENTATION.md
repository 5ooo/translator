# 实现与验证

## 维护流程

1. 在 `src/ts/` 修改相应的输入、文本处理、模型或显示模块；系统依赖和模型安装逻辑位于 `scripts/`。
2. 对照[需求与功能边界](REQUIREMENTS.md)及[命令参考](INTERFACE.md)，更新受影响的文档和行为测试。
3. 在已安装项目环境中运行测试；涉及剪贴板、OCR 或模型的改动还需验证对应的真实资源。
4. 需要分发时，按[安装与配置](INSTALLATION.md)重新构建离线包，并在目标系统测试。

## 自动化测试

只运行不依赖真实模型或 OCR 的测试：

```bash
./bin/python -m pytest -q -m 'not integration' -p no:cacheprovider
```

强制运行真实语言识别、双向 Argos、OCR 和 PLaMo CPU 推理：

```bash
TS_REQUIRE_PLAMO=1 TS_PLAMO_DEVICE=cpu ./scripts/test.sh -q -rs
```

`scripts/test.sh` 设置 `TS_REQUIRE_INTEGRATION=1`，真实集成资源缺失会失败；`TS_REQUIRE_PLAMO=1` 使 PLaMo 缺失也失败。Argos 集成测试在 Python 层禁止网络连接，PLaMo 测试仅允许回环连接。最近结果见[测试报告](TEST_REPORT.md)。

## 桌面剪贴板

桌面协议不能只靠模拟测试验收。先创建独立的 Xvfb 或带输入 seat 的 Weston 测试会话，确认命令 `ts` 可从交互 Bash 解析，再运行：

```bash
./bin/python scripts/verify_clipboard.py --backend x11 --display :198
./bin/python scripts/verify_clipboard.py --backend wayland --display ts-nested-test --runtime-dir /path/to/test-runtime
```

脚本会向指定会话的剪贴板写入测试文字和图片，并比较无参数 `ts` 与显式输入的结果。图片测试需要系统中的 Noto CJK 字体。不要将日常桌面会话作为测试显示器。
