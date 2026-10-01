# 问题发现记录

2026-09-21，基于[上游 2.2 / 330c8e7](UPSTREAM_SOURCE.md)的静态检查。以下为上游实现或表述问题，未修复；不是 OpenCode 或多 agent 特有问题。保留用于实际遇到问题时判断是否优化或换用其他技能，不设自动修复计划。

| 触发条件 / 位置 | 观察与使用时对照 |
| --- | --- |
| 带密钥/邮箱的分页请求失败；[paginate.py](scripts/paginate.py) | 异常可能输出未脱敏 URL 或响应片段；使用该路径前修复或暂避。 |
| 旧式 arXiv ID；[arxiv_atom.py](scripts/arxiv_atom.py) | `hep-th/9901001` 会丢失前缀；对照原始 Atom 链接，不能据截断 ID 回查。 |
| 异常稀疏摘要索引；[openalex_abstract.py](scripts/openalex_abstract.py) | 按首尾跨度构造列表，可能大量占用内存；异常跨度输入不宜直接运行。 |
| Europe PMC 返回 404；[europepmc.md](references/europepmc.md) | 只能说明该端点未返回，不能推断全网无全文或补充数据。 |
| 依赖完整公式/表格/混合段落；[jats_to_text.py](scripts/jats_to_text.py) | 提取会省略部分标签，也可能遗漏 body 直属段落；需要这些内容时对照原 XML。 |
