# research-toolbox

为 Codex 和 OpenCode 保存与分发固定上游技能副本的中转仓库。默认保留完整上游方法、脚本、参考资料、模板、许可证和输出能力；收录不代表宿主专用适配、效果提升或全面运行验证。

## 当前范围与命名

保留清单共 **74 项**，当前实际收录 **69 项**；另 5 项因许可问题暂缓，仅保留分类和上游链接。所有已收录技能保留原始调用名称。

技能使用原始调用名称，**不添加 `-curated`**。仓库名保持不变。`researchwrite` 的上游目录名为 `nature-proposal-writer`，两者关系保留；`nature-shared` 是共享依赖，保留关闭隐式调用的原设置。需要 Nature 共享资料的技能应连同 `nature-shared` 安装。

原有 8 项仅撤销分发名称后缀，保留原固定上游内容、许可证与问题记录。原 `*-curated` 版本说明作为历史记录保留；当前仓库未创建 tags/releases。GitHub 变更不代表本机旧安装已迁移，安装时须避免同名来源冲突。

最新版本选择以 **2026-09-21 本次查询结果**为准：优先最新非草稿、非预发布 release；自建多技能仓库按各技能 release 选择；无 release 时保存默认分支的完整固定提交，明确标为快照。版本、完整提交、目录 tree、取得时间和许可均见各项 `UPSTREAM_SOURCE.md`。

## 分类清单

以下整合原清单的 73 项和 2026-10-03 新增的自建 `zotero-ai-reading`，共 **74 项、7 个大方向、31 个细分方向**，原有分类和顺序不变。74 是保留目录条目数，69 才是本仓库当前可分发技能数。`markdown-mermaid-writing` 来源已按本次决定更正为 K-Dense 的完整技能包；原作者归属与许可保留在来源记录中。

用途和重叠说明沿用用户清单，属于功能定位说明，不是本轮执行测试结论。“高重叠”不表示可以完整替代。

## 导航

| 大方向 | 细分方向数 | Skill 数 |
|---|---:|---:|
| [1. 科研方法、研究设计与评估](#category-1) | 7 | 15 |
| [2. 文献检索、证据与引用管理](#category-2) | 4 | 11 |
| [3. 科研写作、投稿与审稿](#category-3) | 4 | 10 |
| [4. 文档处理、解析与知识管理](#category-4) | 5 | 15 |
| [5. 演示、海报与科研可视化](#category-5) | 4 | 10 |
| [6. 数值计算、数据处理与科学编程](#category-6) | 5 | 10 |
| [7. Agent、技能维护与云计算基础设施](#category-7) | 2 | 3 |
| **合计** | **31** | **74** |

为便于同类比较，`peer-review` 归入“科研写作、投稿与审稿”，`venue-templates` 归入其中的投稿规范分项，`arbor` 归入“Agent、技能维护与云计算基础设施”；分类与条目顺序沿用原清单；分发状态见各行备注。

<a id="category-1"></a>

## 1. 科研方法、研究设计与评估

### 1.1 一体化科研工作流

这是跨检索、写作和评审的上层套件；与后续专业分项有意重叠，不意味着它们全部可被无损替代。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [academic-research-suite](academic-research-suite/) | [Imbad0202/academic-research-skills-codex][repo-2] | 组织研究、综述、论文写作、审稿与实验规划的一体化 ARS 流程。 | 与检索、写作、审稿多项高重叠；区分点是 ARS 命令、角色与交接总控。  已收录；[固定来源](academic-research-suite/UPSTREAM_SOURCE.md)。 |

### 1.2 研究构思、多视角讨论与可检验假设

共同处理开放研究问题；区别在于生成方向、模拟多视角，还是把观察收敛成可检验假设。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [scientific-brainstorming](scientific-brainstorming/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-scientific-brainstorming] | 独立生成并讨论候选研究方向，记录证据、假设、反对意见与决策。 | 与 council 的多视角讨论重叠；侧重科研构思，不把点子当作验证结果。  已收录；[固定来源](scientific-brainstorming/UPSTREAM_SOURCE.md)。 |
| [consciousness-council](consciousness-council/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-consciousness-council] | 用差异化思维角色讨论复杂问题、权衡与创意。 | 科研讨论与 brainstorming 高重叠；特色是通用决策角色库。  已收录；[固定来源](consciousness-council/UPSTREAM_SOURCE.md)。 |
| [hypothesis-generation](hypothesis-generation/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 把观察转成候选假设、竞争解释、判别性预测与可检验研究计划。 | 与 brainstorming 衔接；更侧重“如何证伪/区分”，而非仅扩展点子。  已收录；[固定来源](hypothesis-generation/UPSTREAM_SOURCE.md)。 |

### 1.3 实验设计、样本量与分析方法验证

分别关注研究怎样安排、需要多少样本，以及测量程序是否适用于目标用途。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [experimental-design](experimental-design/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 规划随机化、区组、对照、因子组合、重复与序贯等研究设计。 | 解决“怎样安排实验”；样本量与分析实施分别见同组 power 和统计分项。  已收录；[固定来源](experimental-design/UPSTREAM_SOURCE.md)。 |
| [statistical-power](statistical-power/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-statistical-power] | 计算样本量、最小可检测效应、功效曲线及模拟功效。 | 基础功效与 statistical-analysis 重叠；侧重设计阶段的样本量与模拟功效。  已收录；[固定来源](statistical-power/UPSTREAM_SOURCE.md)。 |
| [analytical-method-validation](analytical-method-validation/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 组织分析方法的验证、确认与转移，检查精密度、准确度及检测能力。 | 验证“测量方法是否适用”；不是一般实验分组或样本量计算。  已收录；[固定来源](analytical-method-validation/UPSTREAM_SOURCE.md)。 |

### 1.4 数据探索、统计推断与测量不确定度

数据体检、假设推断、物理量误差不是同一任务；实现特定贝叶斯模型另见第 6 类 PyMC。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [exploratory-data-analysis](exploratory-data-analysis/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 对受支持文件做缺失、异常、泄漏与变换敏感性等本地探索分析。 | 与 statistical-analysis 的前处理重叠；侧重数据体检与探索，不直接确证假设。  已收录；[固定来源](exploratory-data-analysis/UPSTREAM_SOURCE.md)。 |
| [statistical-analysis](statistical-analysis/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 选择统计检验，检查假设，估计效应量并报告推断结果。 | 方法选择/推断入口；与 EDA、power 部分重叠，PyMC 则偏模型实现。  已收录；[固定来源](statistical-analysis/UPSTREAM_SOURCE.md)。 |
| [uncertainty-and-units](uncertainty-and-units/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 检查单位、量纲与数量级，建立不确定度预算并传播测量误差。 | 专门处理物理量与测量不确定度；不能等同统计显著性检验。  已收录；[固定来源](uncertainty-and-units/UPSTREAM_SOURCE.md)。 |

### 1.5 科学证据与学术作品评价

重在审查证据或评价框架；需要审稿人格式的正式草稿/模拟评审时，对照第 3 类同行评审组。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [scientific-critical-thinking](scientific-critical-thinking/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 评估科学主张、研究设计、偏差、混杂及证据质量。 | 与 peer-review 的证据审查重叠；不要求形成正式审稿信。  已收录；[固定来源](scientific-critical-thinking/UPSTREAM_SOURCE.md)。 |
| [scholar-evaluation](scholar-evaluation/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 对学术作品做定性、可追溯的发展性评价，并审查低风险评估量表。 | 与 critical-thinking 部分重叠；侧重评价量表与改进反馈，不给人员排名。  已收录；[固定来源](scholar-evaluation/UPSTREAM_SOURCE.md)。 |

### 1.6 文本思维模式分析

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [dhdna-profiler](dhdna-profiler/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-dhdna-profiler] | 按 DHDNA 框架描述文本呈现的推理、表达与决策模式。 | 分析对象是文本思维模式，而非研究证据；不等于经验证的认知测量。  已收录；[固定来源](dhdna-profiler/UPSTREAM_SOURCE.md)。 |

### 1.7 研究计划与基金申请

两项均能参与 proposal 写作；一个偏论证流程，一个偏资助机构要求。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [researchwrite](nature-proposal-writer/) | [Yuan1z0825/nature-skills][repo-6] | 起草、修订或审查研究计划、开题报告及项目申请的证据与论证。 | 与 grants 的提案写作重叠；侧重通用论证流程，包名为 nature-proposal-writer。  已收录；[固定来源](nature-proposal-writer/UPSTREAM_SOURCE.md)。 |
| [research-grants](research-grants/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 按资助机构要求组织申请叙事、评审要点、预算与申请材料。 | 相对 researchwrite，侧重 NSF/NIH 等机构规则；模板格式另见 venue-templates。  已收录；[固定来源](research-grants/UPSTREAM_SOURCE.md)。 |

<a id="category-2"></a>

## 2. 文献检索、证据与引用管理

### 2.1 论文发现、网页检索与数据库查询

按检索渠道和返回对象区分，不按“都能找资料”合并。引用清理与全文获取另列。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [paper-lookup](paper-lookup/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 通过多种学术 API 查询论文、标识符、引用、开放全文与仓储记录。 | 与 nature-academic-search 高重叠；侧重明确 API、分页与可复现来源。  已收录；[固定来源](paper-lookup/UPSTREAM_SOURCE.md)。 |
| [nature-academic-search](nature-academic-search/) | [wp-a/nature-academic-search][repo-10] | 协调多源检索、MeSH 策略、引用关系、他引审计与引文文件管理。 | **不默认开启，今后需要时再使用。** |
| [exa-search](exa-search/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 通过 Exa 做网页语义检索、论文类别筛选与 URL 内容提取。 | 与论文检索部分重叠；独立价值是 Exa 搜索与网页提取渠道，非书目 API。  已收录；[固定来源](exa-search/UPSTREAM_SOURCE.md)。 |
| [database-lookup](database-lookup/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 按具名公共数据库的端点、筛选条件与分页规则查询并记录来源。 | 与 paper-lookup 的查询方法重叠；不限于论文、引用等学术记录。  已收录；[固定来源](database-lookup/UPSTREAM_SOURCE.md)。 |

### 2.2 全文获取与结构化实验证据

得到可阅读的原文，与得到服务预抽取的实验字段，是两种不同交付。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [nature-downloader](nature-downloader/) | [Yuan1z0825/nature-skills][repo-6] | 通过开放获取、出版商 API 或授权机构访问获取全文及补充材料。 | **不默认开启，今后需要时再使用。** |
| [bgpt-paper-search](bgpt-paper-search/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 通过 BGPT MCP 返回由论文全文抽取的实验方法、样本量及结果等字段。 | 直接查询结构化实验记录；不同于下载全文，也不能替代原文核验。  已收录；[固定来源](bgpt-paper-search/UPSTREAM_SOURCE.md)。 |

### 2.3 多篇文献综合与单篇深读

综述围绕研究集合；Paper Card 围绕一篇研究的证据链。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [literature-review](literature-review/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 组织多库检索、纳入筛选、研究综合和带核验引用的综述报告。 | 检索由同类工具覆盖一部分；区分点是多篇研究筛选与综合流程。  已收录；[固定来源](literature-review/UPSTREAM_SOURCE.md)。 |
| [nature-paper-card](nature-paper-card/) | [Yuan1z0825/nature-skills][repo-6] | 围绕单篇论文梳理问题、方法、公式、实验—结论证据链与局限。 | 单篇 01–16 节深读卡；不是多篇综述或全文逐句翻译。  已收录；[固定来源](nature-paper-card/UPSTREAM_SOURCE.md)。 |

### 2.4 引用核验与文献库维护

前两项高度重叠但输出侧重点不同；PyZotero 负责库操作，不替代书目信息核验。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [citation-management](citation-management/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-citation-management] | 提取和核验书目元数据，转换标识符，清理并生成 BibTeX。 | 与 ref-verifier 的核引高重叠；更侧重 BibTeX 构建、去重与格式整理。  已收录；[固定来源](citation-management/UPSTREAM_SOURCE.md)。 |
| [nature-ref-verifier](nature-ref-verifier/) | [Yuan1z0825/nature-skills][repo-6] · [说明][src-nature-ref-verifier] | 逐条交叉核验引用字段，识别作者顺序、卷年、页码及 DOI 不一致。 | 与 citation-management 高重叠；侧重字段差异分级与整份引用表核查。  已收录；[固定来源](nature-ref-verifier/UPSTREAM_SOURCE.md)。 |
| [pyzotero](pyzotero/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 通过 Zotero Web API 查询或管理条目、分类、标签与附件。 | 操作文献库而非证明引用正确；创建、修改和删除须单独授权。  已收录；[固定来源](pyzotero/UPSTREAM_SOURCE.md)。 |

<a id="category-3"></a>

## 3. 科研写作、投稿与审稿

### 3.1 论文起草、论证重构与语言润色

三者在修订任务上重叠较多；以“从证据成稿 / 重建论证 / 加工已有语言”区分。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [scientific-writing](scientific-writing/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 起草、修订和审查科研论文或报告，记录证据与一致性检查。 | 与 nature-writing 高重叠；侧重跨期刊证据追溯、报告规范与责任边界。  已收录；[固定来源](scientific-writing/UPSTREAM_SOURCE.md)。 |
| [nature-writing](nature-writing/) | [Yuan1z0825/nature-skills][repo-6] · [说明][src-nature-writing] | 从结果、图表和笔记构建论文论证、章节及首次投稿材料。 | 与 scientific-writing 高重叠；侧重 Nature 系论证指导和首投材料组织。  已收录；[固定来源](nature-writing/UPSTREAM_SOURCE.md)。 |
| [nature-polishing](nature-polishing/) | [Yuan1z0825/nature-skills][repo-6] | 润色、重构或翻译已有学术文本，并处理部分 LaTeX 版式问题。 | 与两项写作技能的修订重叠；侧重已有文字的语言加工及专门排版指导。  已收录；[固定来源](nature-polishing/UPSTREAM_SOURCE.md)。 |

### 3.2 同行评审、模拟审稿与返修回复

前两项比较的是评审流程；response 则服务作者的返修回复，不应混成同一个角色。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [peer-review](peer-review/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 为获授权的稿件、方案或提案准备证据受限、建设性的评审草稿。 | 与 nature-reviewer 高重叠；强调授权评审、保密、报告规范与人工责任。  已收录；[固定来源](peer-review/UPSTREAM_SOURCE.md)。 |
| [nature-reviewer](nature-reviewer/) | [Yuan1z0825/nature-skills][repo-6] · [说明][src-nature-reviewer] | 从审稿人视角模拟投稿前评审，给出有证据依据的 Major/Minor 意见。 | 与 peer-review 高重叠；特色是互盲多评审及冻结后汇总，不是作者回复。  已收录；[固定来源](nature-reviewer/UPSTREAM_SOURCE.md)。 |
| [nature-response](nature-response/) | [Yuan1z0825/nature-skills][repo-6] | 按审稿意见组织逐点回复、rebuttal、返修投稿信与标红修改材料。 | 审稿后作者侧交付；与前两项的审稿人侧评估互补。  已收录；[固定来源](nature-response/UPSTREAM_SOURCE.md)。 |

### 3.3 投稿格式、统计报告与数据声明

都属于投稿准备，但检查对象分别是格式规则、统计表述、数据共享与可用性。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [venue-templates](venue-templates/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 选择期刊、会议或基金模板，检查页数、匿名及提交格式。 | 投稿材料与 writing/grants 重叠；侧重格式与规则，不负责核心科学论证。  已收录；[固定来源](venue-templates/UPSTREAM_SOURCE.md)。 |
| [nature-statistics](nature-statistics/) | [Yuan1z0825/nature-skills][repo-6] | 审查或起草论文中的统计方法、图注、效应量、区间与重复数表述。 | 与统计分析/审稿重叠；侧重“论文如何报告”，不等于重做原始统计分析。  已收录；[固定来源](nature-statistics/UPSTREAM_SOURCE.md)。 |
| [nature-data](nature-data/) | [Yuan1z0825/nature-skills][repo-6] | 撰写数据/代码可用性声明，组织仓储、数据集引用与 FAIR 元数据。 | **不默认开启，今后需要时再使用。** |

### 3.4 共享写作参考与依赖

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [nature-shared](nature-shared/) | [Yuan1z0825/nature-skills][repo-6] | 提供 Nature 系列技能按需引用的共用写作与期刊参考文件。 | 共享依赖而非可替代的独立流程；保留依赖它的技能时不可据此判为冗余。  已收录；[固定来源](nature-shared/UPSTREAM_SOURCE.md)。 |

<a id="category-4"></a>

## 4. 文档处理、解析与知识管理

### 4.1 PDF、Word 与 Excel 基础文件操作

以可用、可编辑或可交付的文件为对象，不等于把文件里的文字抽成 Markdown。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| `pdf` | [anthropics/skills][repo-7] | 读取和提取 PDF，合并、拆分、旋转、加水印，处理表单、加密及 OCR。 | 文件操作层；MarkItDown/LiteParse 的提取功能不能替代整套 PDF 操作。  **暂缓分发：上游许可证禁止再分发**；仅保留上游链接。 |
| `docx` | [anthropics/skills][repo-7] | 创建和修改 Word 文档/模板，处理结构、格式、图片、批注与修订。 | 交付可编辑 Word；转 Markdown 的提取功能不替代 DOCX 编辑与修订。  **暂缓分发：上游许可证禁止再分发**；仅保留上游链接。 |
| `xlsx` | [anthropics/skills][repo-7] | 创建和编辑 Excel 工作簿，处理公式、格式、多表及表格清理。 | 交付含公式的工作簿；与 EDA/文档提取有交集，但不等价。  **暂缓分发：上游许可证禁止再分发**；仅保留上游链接。 |

### 4.2 文档解析、网页净化与 Markdown 转换

这组按“输入范围、输出结构、是否调用远端服务”区分；不把所有 PDF/网页读取都视为等价。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [markitdown](markitdown/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-markitdown] | 将 Office、PDF、网页和部分数据格式转换为面向文本分析的 Markdown。 | 异构格式→Markdown；不追求原版式复刻，坐标需求另看 LiteParse。  已收录；[固定来源](markitdown/UPSTREAM_SOURCE.md)。 |
| [liteparse](liteparse/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-liteparse] | 本地抽取带边界框的页面文本/JSON，支持 OCR 与页面 PNG。 | 提供空间坐标和页面图；不直接生成 Markdown，不是普通转换器替身。  已收录；[固定来源](liteparse/UPSTREAM_SOURCE.md)。 |
| [mineru-api-batch-convert](mineru-api-batch-convert/) | [kangjl535-create/custom-agent-skills][repo-4] | 在 Windows 上将授权本地/Zotero PDF 经 MinerU API 转成 Markdown 与图片。 | 自建；特色是同目录批处理、恢复/审计和既有输出保护，不是纯本地解析。  已收录；[来源记录](mineru-api-batch-convert/UPSTREAM_SOURCE.md)。 |
| [defuddle](defuddle/) | [kepano/obsidian-skills][repo-9] | 将网页正文去除导航和杂项后转换为干净 Markdown。 | 网页→Markdown 与 MarkItDown 重叠；侧重正文清理，不覆盖 Office/PDF 操作。  已收录；[固定来源](defuddle/UPSTREAM_SOURCE.md)。 |

### 4.3 实验记录与 Markdown 内容编写

共同生成文本笔记，但分别约束转录忠实度、Obsidian 语法，以及通用文档/Mermaid 图。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [handwritten-labnote-to-markdown](handwritten-labnote-to-markdown/) | [kangjl535-create/custom-agent-skills][repo-4] | 把手写实验记录映射到用户提供的 Markdown 模板，保留来源和不确定处。 | 自建；模板解耦、忠实转录和缺项留空；不是单纯 OCR/格式转换。  已收录；[来源记录](handwritten-labnote-to-markdown/UPSTREAM_SOURCE.md)。 |
| [obsidian-markdown](obsidian-markdown/) | [kepano/obsidian-skills][repo-9] | 编写含双链、嵌入、callout、属性与标签的 Obsidian Markdown。 | 普通 Markdown 与 Mermaid 写作重叠；特色是 Obsidian 方言语法。  已收录；[固定来源](obsidian-markdown/UPSTREAM_SOURCE.md)。 |
| [markdown-mermaid-writing](markdown-mermaid-writing/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 按样式指南与模板编写 Markdown 文档及 Mermaid 文本图。 | 普通 Markdown 重叠；侧重多类 Mermaid 图和可移植文本图，不等于 Canvas。  已收录；[固定来源](markdown-mermaid-writing/UPSTREAM_SOURCE.md)。 |

### 4.4 Obsidian 视图、画布与仓库操作

Bases、Canvas、CLI 分别是视图格式、画布格式、应用操作接口，不能仅因都属于 Obsidian 而合并。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [obsidian-bases](obsidian-bases/) | [kepano/obsidian-skills][repo-9] | 创建 .base 文件，用视图、筛选、公式和汇总组织笔记属性。 | 数据库式笔记视图；不同于 Canvas 的自由节点布局或 CLI 的操作接口。  已收录；[固定来源](obsidian-bases/UPSTREAM_SOURCE.md)。 |
| [json-canvas](json-canvas/) | [kepano/obsidian-skills][repo-9] | 创建和编辑 .canvas 文件中的节点、连线、分组与空间布局。 | 图形化画布结构；与 Mermaid 题材可重叠，但文件格式和编辑方式不同。  已收录；[固定来源](json-canvas/UPSTREAM_SOURCE.md)。 |
| [obsidian-cli](obsidian-cli/) | [kepano/obsidian-skills][repo-9] | 通过 CLI 搜索和管理 vault、笔记、任务、属性及插件/主题调试。 | 操作正在使用的 Obsidian 环境；不替代 Markdown/Base/Canvas 的格式知识。  已收录；[固定来源](obsidian-cli/UPSTREAM_SOURCE.md)。 |

### 4.5 研究资料知识库与问答系统

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [open-notebook](open-notebook/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 部署或使用自托管研究资料系统，摄取资料、检索、问答、摘要与播客。 | 独立知识库应用；与解析/笔记工具功能交叉，但包含索引与多源问答系统。  已收录；[固定来源](open-notebook/UPSTREAM_SOURCE.md)。 |
| [zotero-ai-reading](zotero-ai-reading/) | [kangjl535-create/custom-agent-skills][repo-4] | 为未读 Zotero 文献做 AI 阅读：按用户配色的高亮、公式/图表框和“AI：”批注（经用户粘贴的脚本写入 Zotero），并生成 BibNotes 兼容的 Obsidian 笔记。 | 自建；依赖 MinerU Markdown、Zotero 9 本地 API、Better BibTeX 与 BibNotes Formatter；不直接改动 Zotero，与 pyzotero 的通用文献库操作不同。  已收录；[来源记录](zotero-ai-reading/UPSTREAM_SOURCE.md)。 |

<a id="category-5"></a>

## 5. 演示、海报与科研可视化

### 5.1 科研演讲规划与论文转演示

二者都能参与科研 PPT；论文转演示强调输入证据，通用科研演讲强调受众、结构和时长。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [scientific-slides](scientific-slides/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 规划科研报告、会议或答辩的演示结构、时间安排与视觉检查。 | 与 paper2ppt 重叠；覆盖更广科研演讲及 Beamer，不限单篇论文。  已收录；[固定来源](scientific-slides/UPSTREAM_SOURCE.md)。 |
| [nature-paper2ppt](nature-paper2ppt/) | [Yuan1z0825/nature-skills][repo-6] · [说明][src-nature-paper2ppt] | 将科研论文或阅读笔记转成中文 PPTX，组织证据叙事、原图与讲稿。 | 与 scientific-slides 重叠；专门处理论文类型、中文叙事和选图链。  已收录；[固定来源](nature-paper2ppt/UPSTREAM_SOURCE.md)。 |

### 5.2 PPTX 制作、重构与演讲备注

普通新建、改稿和 notes 确实有重叠；文件结构操作、视觉资产复用、基于现有画面的讲稿准备各有侧重点。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| `pptx` | [anthropics/skills][repo-7] · [说明][src-pptx] | 创建、读取、编辑与重组 PPTX，处理模板、布局、备注和文件结构。 | 常规制作与 ppt-master 高重叠；侧重通用 PPTX/OOXML 操作与包校验。  **暂缓分发：上游许可证禁止再分发**；仅保留上游链接。 |
| [ppt-master](ppt-master/) | [hugohe3/ppt-master][repo-8] | 制作或重构可编辑演示，复用品牌/样式/布局模板，增强动画与旁白。 | 覆盖普通新建/改稿；差异在模板资产复用、视觉重构、动画和旁白。  已收录；[固定来源](ppt-master/UPSTREAM_SOURCE.md)。 |
| `ppt-speech-writer` | [AI272/speaker][repo-1] | 检查现有 PPTX 的文本、结构和画面，写逐页学术讲稿并注入备注区。 | 写 notes 与前两项重叠；特色是现有幻灯片逐视觉元素核对后写讲稿。  **暂缓分发：尚未找到再分发许可证**；仅保留上游链接。 |

### 5.3 学术会议海报

共同处理海报叙事与版面，但源文件与后续人工编辑方式不同。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [latex-posters](latex-posters/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 使用 beamerposter、tikzposter 或 baposter 排版科研会议海报。 | 与 pptx-posters 交付目的相同；路线为 LaTeX 源码与编译排版。  已收录；[固定来源](latex-posters/UPSTREAM_SOURCE.md)。 |
| [pptx-posters](pptx-posters/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 生成可编辑 PowerPoint 科研海报，检查物理尺寸、打印及来源信息。 | 与 latex-posters 内容重叠；路线为可编辑 PPTX，不需要 LaTeX 工程。  已收录；[固定来源](pptx-posters/UPSTREAM_SOURCE.md)。 |

### 5.4 真实数据科研绘图与期刊图形

三者均可参与论文图；区分底层绘图控制、数据表达/导出审查，以及论文图形叙事与 R 等额外路线。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [matplotlib](matplotlib/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-matplotlib] | 精细控制 Python 图形对象、坐标、布局及 PNG/PDF/SVG 导出。 | 常规绘图与另两项重叠；侧重底层对象/API 的精细控制，不能据常规重叠判为完全覆盖。  已收录；[固定来源](matplotlib/UPSTREAM_SOURCE.md)。 |
| [scientific-visualization](scientific-visualization/) | [K-Dense-AI/scientific-agent-skills][repo-3] · [说明][src-scientific-visualization] | 规划与审查真实数据图、多面板、不确定性、可访问性与期刊导出。 | 与 nature-figure 高重叠；侧重 Python 多绘图库及数据表达/导出审查。  已收录；[固定来源](scientific-visualization/UPSTREAM_SOURCE.md)。 |
| [nature-figure](nature-figure/) | [Yuan1z0825/nature-skills][repo-6] · [说明][src-nature-figure] | 制作和审查投稿图形，覆盖 Python/R、多面板及另行指定的 AI 示意图。 | 与 visualization 高重叠；区分点是 R 路线、论文论证和生成式示意图分支。  已收录；[固定来源](nature-figure/UPSTREAM_SOURCE.md)。 |

<a id="category-6"></a>

## 6. 数值计算、数据处理与科学编程

### 6.1 资源约束、分块存储与并行加速

对应“能用多少资源 / 数据怎么存 / 任务怎么分块调度 / 是否迁移 GPU”四个层次，可以组合而非互删。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [get-available-resources](get-available-resources/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 检测当前进程实际可用的 CPU、内存、磁盘及 GPU/调度限制。 | 只做资源体检和规划；不执行分布式调度、存储转换或 GPU 加速。  已收录；[固定来源](get-available-resources/UPSTREAM_SOURCE.md)。 |
| [zarr-python](zarr-python/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 用 Zarr 分块、压缩和按需读写多维数组，衔接本地或云对象存储。 | 存储格式/访问层；与 Dask 互补，不是分布式计算调度器。  已收录；[固定来源](zarr-python/UPSTREAM_SOURCE.md)。 |
| [dask](dask/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 把数组、表格与文件处理任务分块并行，扩展到超内存或集群。 | 执行/调度层；可与 Zarr 组合，不替代存储格式或专门 GPU 算法。  已收录；[固定来源](dask/UPSTREAM_SOURCE.md)。 |
| [optimize-for-gpu](optimize-for-gpu/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 用 CuPy、Numba CUDA、RAPIDS、Warp 等改造适合 GPU 的 Python 计算。 | 设备加速层；与 Dask 有并行交集，但不是所有大数据任务都需 GPU。  已收录；[固定来源](optimize-for-gpu/UPSTREAM_SOURCE.md)。 |

### 6.2 数值工作流与精确符号计算

以实际项目语言和所需数学表示区分，而不是断言 MATLAB 不能做符号计算。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [matlab](matlab/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 构建、审查或迁移 MATLAB/Octave 数值项目，处理 MAT 文件与 Python 互操作。 | 侧重 MATLAB 工程和语言迁移；不是 SymPy 的纯符号工具说明。  已收录；[固定来源](matlab/UPSTREAM_SOURCE.md)。 |
| [sympy](sympy/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 做精确符号代数、微积分、方程、矩阵运算和代码生成。 | 侧重精确符号推导；与数值计算互补，不以浮点近似代替精确结果。  已收录；[固定来源](sympy/UPSTREAM_SOURCE.md)。 |

### 6.3 贝叶斯建模与多目标优化

概率推断与 Pareto 寻优的目标不同；同属建模，并不表示能力重复。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [pymc](pymc/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 实现贝叶斯层级模型、MCMC/变分推断、后验检查和模型比较。 | 补充统计方法技能的模型实现；不是 PyMoo 的多目标寻优。  已收录；[固定来源](pymc/UPSTREAM_SOURCE.md)。 |
| [pymoo](pymoo/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 求解有约束的多目标优化，产生 Pareto 解集并比较权衡。 | 优化目标与约束；不同于 PyMC 的参数概率推断。  已收录；[固定来源](pymoo/UPSTREAM_SOURCE.md)。 |

### 6.4 图与网络分析

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [networkx](networkx/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 构建和分析图/网络，计算连通性、路径、中心性、聚类与社区。 | 显式节点—边拓扑算法；与通用数组处理、绘图不能简单互换。  已收录；[固定来源](networkx/UPSTREAM_SOURCE.md)。 |

### 6.5 实验流场测量

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [openpiv](openpiv/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 从 PIV 图像对提取速度场，验证向量并计算涡量、应变等指标。 | 图像对→实验测量流场；不是 CFD 求解器或一般图像查看器。  已收录；[固定来源](openpiv/UPSTREAM_SOURCE.md)。 |

<a id="category-7"></a>

## 7. Agent、技能维护与云计算基础设施

### 7.1 迭代优化与技能生命周期管理

一个反复运行试验提升目标表现；另一个维护技能成品的测试、版本和分发。

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [arbor](arbor/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 以目标和评估器驱动假设树分支试验，迭代改进代码、模型或数据管线。 | 运行并比较改进实验；不同于仅生成假设或维护技能发布版本。  已收录；[固定来源](arbor/UPSTREAM_SOURCE.md)。 |
| [homemade-skill-lifecycle](homemade-skill-lifecycle/) | [kangjl535-create/custom-agent-skills][repo-4] | 创建、修订、测试、版本化和发布自建技能，处理日常使用中记录的缺陷，并交接 CC Switch 更新。 | 自建（原名 codex-skill-lifecycle）；管理 skill 成品生命周期，不替代 Arbor 的目标驱动试验搜索。  已收录；[来源记录](homemade-skill-lifecycle/UPSTREAM_SOURCE.md)。 |

### 7.2 远端计算与服务部署

| Skill 名称 | GitHub 来源仓库 | 用途简介 | 备注：区分与重叠 |
|---|---|---|---|
| [modal](modal/) | [K-Dense-AI/scientific-agent-skills][repo-3] | 在云容器上执行 Python/GPU 工作负载，部署模型、服务和批处理。 | 远端运行平台；与本地 GPU 优化/Dask 执行可组合，不互为替代。  已收录；[固定来源](modal/UPSTREAM_SOURCE.md)。 |


## 使用、验证与更新

CC Switch 仓库地址：`https://github.com/kangjl535-create/research-toolbox`，分支 `main`。选择所需技能安装；本次只维护 GitHub 分发内容，不操作本机安装、应用开关、模型、角色或权限。

本轮检查固定上游文件身份、完整文件范围、元数据、许可证、名称与共享依赖路径，以及发布 ZIP 与目录内容的一致性。没有执行科研任务、模型工作流或外部服务调用，没有安装运行依赖。上游格式与严格校验器的兼容性观察写入对应 `KNOWN_ISSUES.md`；记录不代表修复。仓库未设置 CI，不把本地检查称为 CI 通过。

更新时按各项来源记录比较新的 release/提交与技能目录 tree；仓库发布号变化不证明每项技能都变化。人工审阅依赖、许可和内容差异后再采用，Git 历史、固定 tag/release 和单技能 ZIP 保留版本；不自动跟随上游。

## 许可与暂缓项

仓库维护文档采用 [MIT License](LICENSE)。**各技能依其自身许可证分发，并非全部适用 MIT**。K-Dense、Obsidian、自建技能及 PPT Master 保留其 MIT 声明与组件许可；Nature 技能保留各自许可：`nature-downloader` 为目录内 MIT，另附仓库级 Apache-2.0 声明；其他已收录 Yuan1z0825/nature-skills 技能为 Apache-2.0；`nature-academic-search` 为 MIT；ARS 使用 **CC-BY-NC-4.0（非商业）**，须遵守署名、非商业使用和组件声明。Markdown/Mermaid 包同时保留原作者 Apache-2.0 声明。

`pdf`、`docx`、`xlsx`、`pptx`：所核查的 Anthropic 上游许可证明确限制复制、改作及再分发，未上传技能原文。`ppt-speech-writer`：所核查的 AI272/speaker v0.8.0 未找到再分发许可证，暂不上传。以上 5 项经用户决定暂缓，不用来源占位文件伪装为已收录技能。


<!-- Repository and documentation references. Standard Markdown links remain portable. -->
[repo-1]: https://github.com/AI272/speaker
[repo-2]: https://github.com/Imbad0202/academic-research-skills-codex
[repo-3]: https://github.com/K-Dense-AI/scientific-agent-skills
[repo-4]: https://github.com/kangjl535-create/custom-agent-skills
[repo-5]: https://github.com/SuperiorByteWorks-LLC/agent-project
[repo-6]: https://github.com/Yuan1z0825/nature-skills
[repo-7]: https://github.com/anthropics/skills
[repo-8]: https://github.com/hugohe3/ppt-master
[repo-9]: https://github.com/kepano/obsidian-skills
[repo-10]: https://github.com/wp-a/nature-academic-search
[curated]: https://github.com/kangjl535-create/research-toolbox
[curated-readme]: https://github.com/kangjl535-create/research-toolbox/blob/main/README.md
[src-scientific-brainstorming]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-brainstorming/SKILL.md
[src-consciousness-council]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/consciousness-council/SKILL.md
[src-dhdna-profiler]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/dhdna-profiler/SKILL.md
[src-statistical-power]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/statistical-power/SKILL.md
[src-citation-management]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/citation-management/SKILL.md
[src-nature-ref-verifier]: https://github.com/Yuan1z0825/nature-skills/blob/main/skills/nature-ref-verifier/SKILL.md
[src-nature-writing]: https://github.com/Yuan1z0825/nature-skills/blob/main/skills/nature-writing/SKILL.md
[src-nature-reviewer]: https://github.com/Yuan1z0825/nature-skills/blob/main/skills/nature-reviewer/SKILL.md
[src-markitdown]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/markitdown/SKILL.md
[src-liteparse]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/liteparse/SKILL.md
[src-nature-paper2ppt]: https://github.com/Yuan1z0825/nature-skills/blob/main/skills/nature-paper2ppt/SKILL.md
[src-pptx]: https://github.com/anthropics/skills/blob/main/skills/pptx/SKILL.md
[src-matplotlib]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/matplotlib/SKILL.md
[src-scientific-visualization]: https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-visualization/SKILL.md
[src-nature-figure]: https://github.com/Yuan1z0825/nature-skills/blob/main/skills/nature-figure/SKILL.md
