# 问题发现记录

针对上游 `330c8e7` / 1.8 的静态观察；未修复，非全面质量验收，也非 OpenCode 特有问题。实际遇到相应路径时据此决定规避、优化或替换。

- 校验假通过：`scripts/validate_presentation.py:103–109,153–158,296–305` 缺 PDF/PPTX 库时仅 warning，仍可能 PASSED/exit 0；未知格式同类。应确认具体检查实际执行，不能用退出码证明成品质量。
- 页序：`scripts/slides_to_pdf.py:31–71` 将显式文件列表 set 去重后按 basename 排序，不保留给定顺序。暂用单目录零填充编号，并核对输出页序。
- 现有 pptx 接口差异：`references/visual_review_workflow.md:125` 的 thumbnail `--individual` 不存在；`assets/powerpoint_design_guide.md:514` 的 add_slide 不接受 packed PPTX 与 `-o`。逐页图可先导 PDF 再用 `pdf_to_images.py`；新增页应在派生解包目录调用 add_slide，并按返回页ID更新播放列表后打包。这里仅记录，未改上游指南。
- 外发与凭据：两组生成 wrapper/AI 脚本会沿 cwd 祖先找 `.env`，并向 OpenRouter 发送提示/附件/审阅图片。仅在该内容和凭据入口已授权时用 AI 路径；本次未运行。
- 部署/写入条件：原文 `skills/pptx/...` 等路径须解析到实际安装位置和接口；按具体输出满足 PDF/PPTX/TeX 依赖。validator 的 TeX 路径会调用编译器并在源文件旁生成/覆盖产物（225–260），需使用派生副本；不是只读检查。嵌套 openclaw 元数据此前已被 OpenCode 发现，无证据需要删除。
