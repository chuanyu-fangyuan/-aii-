# 评测与质量门禁（EVALS）

> 这个项目怎么证明「做得对」：三份评测脚本 + 单元测试 + 逐指标回归门禁。
> 所有数字都来自实跑，未达标项**不隐藏**，并在每次跑门禁时打印公示。
> 最后核对时间：2026-09-23。

## 1. 全貌

```
                       ┌─────────────── CI（.github/workflows/update.yml 的 evals 作业）───────────────┐
单元测试 ──────────────►  pytest tests/ --cov=. --cov-fail-under=50      覆盖率熔断线 50%（实测 58.11%）
静态检查 ──────────────►  ruff check .（规则见 ruff.toml）                 0 error
质量指标 ──────────────►  python evals/run_all.py --gate-config evals/baseline.json
                       └────────────────────────────────────────────────────────────────────────────┘
                                                        │ 任一不过 → deploy 不执行
```

三份评测脚本各自独立可跑，也可由 `evals/run_all.py` 统一调度（它负责跑脚本、判定门禁、写报告）。

| 评测 | 脚本 | 数据集 | 成本 | 当前状态 |
|---|---|---|---|---|
| 检索 | `evals/eval_retrieval.py` | `evals/retrieval_queries.jsonl`（10 条） | 0（本地嵌入） | ✅ 可跑，**指标未达标**（见 §2） |
| 分类 | `evals/eval_classify.py` | `evals/dataset.jsonl`（30 条，**0 条已标注**） | 0 | ⚠️ 未启用（缺人工标注，见 §3） |
| RAG 问答 | `evals/eval_rag.py` | `evals/rag_qa.jsonl`（20 题） | 约 ¥0.12/轮（v2 单版本） | ✅ 达标（见 §4） |

## 2. 检索评测

**指标定义**（对 10 条 query 逐条计算后取平均）：

| 指标 | 定义 |
|---|---|
| `recall@k` | 命中数 / 该 query 的相关文档总数（k=5） |
| `mrr` | 第一个命中结果的排名倒数（1/rank） |
| `ndcg@k` | 折扣累计增益 / 理想 DCG，命中越靠前分越高 |

**实跑结果**（`python evals/eval_retrieval.py --json`）：

| 指标 | 数值 | 熔断线 | 状态 |
|---|---|---|---|
| Recall@5 | **0.2600** | 0.65 | ❌ **未达标** |
| MRR | 0.3900 | — | 参考值 |
| NDCG@5 | 0.2388 | — | 参考值 |

**为什么低**（`report_week2.md` 的结论，未变）：

1. **测试集构造方式**：`relevant_ids` 由关键词匹配生成，覆盖面窄于语义检索 —— 语义上相关但没含关键词的新闻会被算作「未命中」；
2. **嵌入模型**：`bge-small-zh-v1.5`（512 维轻量模型）对专业术语区分度有限；
3. **BM25 分词**：中文按单字切分（`retrieval._tokenize`），词级信号丢失。

**调优方向**（按性价比排序）：① 引入 jieba 做词级切分（改动最小）；② 用人工标注替换关键词匹配的测试集（否则指标本身不可信）；③ 提升向量权重（当前 `VECTOR_WEIGHT = 0.6`）；④ 换 `bge-base-zh-v1.5`。

> **门禁怎么处理未达标项**：`target = 0.65` 只公示不拦截，只做回归拦截（跌破 `snapshot - tolerance` 才拦）。把未达标项当硬阈值会让每次运行都失败、部署被永久卡住 —— 这是踩过的坑（README 案例十一）。**门禁的职责是防退化，不是催达标。**

## 3. 分类评测

**指标定义**：逐类统计 TP/FP/FN 后取 **macro-F1**（8 个分类：模型 / 应用 / 芯片硬件 / 开源 / 融资创业 / 政策监管 / 研究突破 / 其他），熔断线 0.70。

**当前状态：未启用**。`evals/dataset.jsonl` 有 30 条抽样，但 `expected_category` **全部为空** —— 评测脚本会打印「数据集中没有已标注的样本」并提前返回，**不产出任何指标**。

门禁对此的处理是显式 WARN（`未产出任何指标，本次不参与门禁`），而不是静默通过 —— 「没指标」不等于「通过」。

**启用步骤**：

```bash
python evals/create_dataset.py --count 30 --seed 42   # 抽样生成待标注集（已有）
# 人工填写每行 expected_category / expected_verification
python evals/eval_classify.py --json                  # 确认产出 f1
# 把 f1 登记进 evals/baseline.json 的 rules["eval_classify.py"]
```

## 4. RAG 问答评测

**为什么自实现**：`ragas` 官方库 0.2.x / 0.4.x 硬依赖 `langchain_community.chat_models.vertexai`，与 Agent 所需的 langchain 1.x 生态互斥（详见 README 案例八）。为保住 Agent 运行环境，按 RAGAS 论文口径用 DeepSeek 自实现三项指标。

**指标定义**（20 题全量，一次 judge 调用同时给出）：

| 指标 | 定义 | 熔断线 |
|---|---|---|
| `faithfulness` | 把答案拆成原子断言，被检索上下文支持的断言占比 | **0.75**（Week 4 里程碑） |
| `answer_relevancy` | 答案对问题的针对性与完整度（1-5 归一到 0-1） | — |
| `context_precision` | 相关资料是否排在检索结果前部（precision@rank 均值） | — |
| `rubric` | LLM-as-judge 综合分（有用性/引用规范/无编造），1-5 | 3.5 |

**实跑结果**（v2 Prompt，20 题，`report_week3.md`）：

| 指标 | v1 | v2 | 达标线 | 状态 |
|---|---|---|---|---|
| faithfulness | 0.97 | **1.00** | 0.75 | ✅ |
| answer_relevancy | 0.98 | 0.98 | — | ✅ |
| context_precision | 0.9620 | 0.9585 | — | ✅ |
| rubric | 4.9 | 4.9 | 3.5 | ✅ |

**v1 vs v2 的结论**：三项指标差异 ≤ 0.03，本质是「语料仅千余条 + context_precision 已 0.9+ → 答案就是抄写+归纳，两种 Prompt 都贴着天花板」。仍切 v2 的理由是**行为**而非分数：20 题 0 编造（v1 有 1 条无支持断言）、陷阱题（#19/#20）「声明不足而非编造」的行为更稳。情报站的价值排序是「不编造 > 多说 2%」。

**已知局限（必须一起看）**：

1. **裁判与生成模型同源**（都是 DeepSeek），faithfulness 1.00 有自我偏好风险 → 缓解手段是不依赖裁判的独立检查点：`context_precision` 可人工抽查、陷阱题可直读答案验证；
2. **样本量小**（20 题），不足以分辨 ≤0.03 的差异；
3. 语料规模（千余条）决定了天花板，语料扩大后需复测。

## 5. Embedding 一致性

`python build_embeddings.py --verify` 对比「库内存储向量」与「重新推理向量」的余弦相似度：

| 指标 | 数值 | 标准 | 状态 |
|---|---|---|---|
| cos_sim | 1.000000 | > 0.99 | ✅ PASS |

作用：确保向量写入/读取（BLOB 存取）没有精度损失，否则检索结果会漂移。

## 6. 回归门禁（`evals/baseline.json`）

规则是**逐指标**声明的，不是单一全局阈值：

```json
"eval_rag.py": {
  "faithfulness": { "snapshot": 1.0, "tolerance": 0.03, "floor": 0.75 },
  "rubric":       { "snapshot": 4.9, "tolerance": 0.3,  "floor": 3.5 }
},
"eval_retrieval.py": {
  "recall@k": { "snapshot": 0.26, "tolerance": 0.06, "floor": null, "target": 0.65 }
}
```

| 字段 | 含义 | 行为 |
|---|---|---|
| `floor` | 达标的硬下限 | 低于则**拦截** |
| `snapshot` + `tolerance` | 记录时的水平 + 允许抖动 | 跌破则**拦截** |
| `target` | 尚未达到的目标 | 只**公示**，不拦截 |

**拦截能力实测**（合成数据，避免为了验证而真的把质量改坏）：

```
拦截 | faithfulness 跌破达标线 0.75 | faithfulness=0.7 < 下限 0.75
拦截 | 检索 recall 下滑到 0.10      | recall@k=0.1 较基线 0.26 下滑超过 0.06
拦截 | 评测脚本跑不通               | eval_rag.py: 评测未跑通（failed）
放行 | 一切正常                     |
```

**成本分流**（否则门禁本身成为成本黑洞）：RAG 评测一轮 80 次 LLM 调用（约 ¥0.12–0.25），而工作流每 3 小时被触发一次。因此按触发来源分流：

| 触发 | 行为 |
|---|---|
| `push`（代码变更） | 跑完整评测（含 LLM 指标） |
| `workflow_dispatch`（定时数据更新） | `--skip-llm`：只跑零成本的检索/分类评测 |

## 7. 单测与 lint

| 项 | 阈值 | 实测 |
|---|---|---|
| 覆盖率（`pytest --cov=.`） | ≥ **50%**（熔断线） | **58.11%**（146 passed / 2 skipped） |
| Lint（`ruff check .`） | 0 error | ✅ All checks passed |

**覆盖率口径**（`.coveragerc`）：排除 `tests/`、`evals/`、`import_baseline.py`（一次性导入脚本）。理由：把测试与脚手架算进分母会稀释数字，看着好看但没有意义。

**测试的硬约束**（三条，都有对应的防回退断言）：

1. 不联网 —— HTTP 一律用假对象替换；
2. 不花钱 —— 没有任何真实 LLM 调用；
3. 不污染生产库 —— 全部跑在临时库上（早期 API 测试曾往 `data/news.db` 的 `pending_review` 写入 4 行测试数据，已修复并加断言）。

## 8. 已知差距清单（统一收口）

| 差距 | 影响 | 状态 |
|---|---|---|
| 检索 Recall@5 = 0.26 < 0.65 | 检索质量不达标 | 已公示，调优方向见 §2 |
| 分类评测无人工标注集 | 分类质量无度量 | 待人工标注后启用（§3） |
| 裁判与生成模型同源 | RAG 分数可能偏乐观 | 已披露 + 独立检查点缓解（§4） |
| 评测样本量小（10 / 30 / 20） | 分辨力有限 | 已披露 |
| 峰谷时段判断待校准 | 成本估算可能差 2 倍 | 待埋点覆盖率满 100% 后用账单校准（README 首次对账） |
| black 未纳入强制检查 | 风格不统一 | 有意为之：全量重排会产生 900+ 行纯格式 diff（README 已知限制） |

## 9. 怎么跑

```bash
# 全部评测 + 门禁（本地）
python evals/run_all.py --gate-config evals/baseline.json

# 只跑零成本部分（省钱）
python evals/run_all.py --skip-llm

# 单项
python evals/eval_retrieval.py --json
python evals/eval_classify.py --json
python evals/eval_rag.py --prompt v2 --limit 20 --json

# 单测与覆盖率
pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=50

# 嵌入一致性
python build_embeddings.py --verify
```

| 命令 | 成本 | 耗时（本机实测） |
|---|---|---|
| `run_all.py --skip-llm` | ¥0 | 约 20 秒（含嵌入模型加载） |
| `run_all.py`（含 v1+v2） | 约 ¥0.25 | 约 6–8 分钟 |
| `pytest tests/`（含覆盖率） | ¥0 | 约 50 秒 |
