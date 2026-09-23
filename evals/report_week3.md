# Week 3 评测报告：RAG 评测 v2（RAGAS 口径三指标 + LLM-as-judge）

日期：2026-09-22 ｜ 执行脚本：`evals/eval_rag.py` ｜ 数据：`evals/rag_qa.jsonl`（20 组问答对）｜ 明细：`evals/rag_eval_results.jsonl`

## 0. 方法论披露（重要）

**ragas 官方库未能用于本项目**：ragas 0.2.15 / 0.4.3 均在包初始化时硬依赖
`langchain_community.chat_models.vertexai`（该模块在 langchain-community 0.4.x 已移除），
而本项目 Agent（Week 3 核心产出）基于 langchain 1.x + langgraph 1.x 新栈开发，二者在同一个
venv 中互斥。曾尝试把整套 langchain 降级到 0.3.x 旧栈来迁就 ragas，结果与 Agent 环境冲突，
且 Windows 下 pip 的安全删除机制不可用，最终放弃降级、恢复 Agent 环境。

**替代方案**：按 RAGAS 论文口径用 DeepSeek（裁判模型 = 生成模型，已如实标注局限）自实现三项指标：

| 指标 | 实现口径 | 局限 |
|---|---|---|
| faithfulness | 把答案拆成原子断言，逐条判断能否由上下文推出，得分 = 被支持断言占比 | 裁判与生成同模型，可能偏乐观 |
| answer_relevancy | 裁判按 1-5 打分答案对问题的针对性与完整度，归一到 0-1 | 原版基于嵌入相似度，此处为 LLM 判断 |
| context_precision | 裁判逐条标注检索片段相关性，得分 = 相关片段处 precision@rank 均值 | 与原版定义一致 |
| rubric（LLM-as-judge） | 综合有用性 / 引用规范 / 无编造，1-5 分 | 自定义 rubric |

评测脚本不依赖 ragas，复用与线上 `/ask` 完全相同的检索（`retrieval.search`，top_k=5）与提示词模板，保证评测口径与生产一致。

## 1. v1 / v2 Prompt 对比实验

- v1：`prompts/rag_v1.txt`（Week 2 上线版：基于资料回答 + [编号] 引用 + 资料不足声明）
- v2：`prompts/rag_v2.txt`（Day 20 新版：强制「每条事实紧跟引用」、首行结论先行、不足先声明再给部分信息、禁止无时间标注写时间）
- 20 题全部来自库内真实新闻（含 2 道「资料不足」陷阱题：#19 联邦立法、#20 GPT-6）

| 指标（0-1，rubric 1-5） | v1 | v2 | 差值 |
|---|---|---|---|
| faithfulness | 0.99 | **1.00** | +0.01 |
| answer_relevancy | **0.99** | 0.97 | -0.02 |
| context_precision | **0.93** | 0.90 | -0.03 |
| rubric | **4.95** | 4.85 | -0.10 |

逐题差异：faithfulness v2 赢 1 题、输 0 题；relevancy v2 输 2 题；context_precision 各 1 题，其余 18-19 题持平。

## 2. 结论

1. **v1 与 v2 差异在噪声范围内（|Δ| ≤ 0.03）**。语料只有 900 余条、检索质量高（context_precision 0.9+），
   答案基本是「抄写 + 归纳」，两种 prompt 都接近天花板——小语料 + 好检索会让 prompt 工程的收益钝化。
2. **v2 在其设计目标（忠实度）上确实略优**：20 题 0 编造（v1 有 1 题存在 1 条未被支持的断言），
   且陷阱题 #19/#20 的「先声明不足、再给部分信息」格式更稳定。
3. **采用决策：线上切换为 v2**。情报站对「不编造」的优先级高于「答案稍多 2% 的相关性」；
   等语料扩大到数千条、检索噪声上升后，v2 的防幻觉规则预期收益会更明显，值得届时复测。
4. **两条陷阱题的独立发现**：RAG 系统本身对「资料不足」类问题的抵抗力已经达标
   （v1/v2 都正确声明无法回答而未编造），这是 Week 2 幻觉防护（引用 ID 校验 + 资料不足声明）的验证。

## 3. 成本核算（本轮评测）

| 项 | 数值 |
|---|---|
| LLM 调用次数 | 80（20 题 × 2 prompt × [生成 1 + 裁判 1]） |
| 输入 tokens | 56,521 |
| 输出 tokens | 14,786 |
| 总耗时 | 2 分 45 秒（含本地嵌入检索） |
| 估算成本 | ≈ ¥0.5（DeepSeek chat 官方牌价估算，非实测账单） |

## 4. Week 3 里程碑核对

- [x] Agent 能自主完成一次完整情报任务（Day 16/18 已验证，产出 1338 字报告）
- [x] 条件边补证逻辑生效（verify 可疑 → 回 gather，最多 2 轮，graph.py 有验证记录）
- [x] HITL 审核流可用（pending_review 表 + POST /review/{id} + web/review.html，未审核不进线上）
- [x] RAGAS 三项指标有数值（自实现口径，方法论已披露）
- [x] Prompt v1/v2 对比表（本文 §1）
- [x] MCP Server 可用（Day 19：5 工具全部列出并可调用，`tests/verify_mcp.py`）
