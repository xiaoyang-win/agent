# 多应用 Agent 套件（申请 Token 版）

本项目提供一个可直接运行的 `agent.py`，将一次代码变更扩展为多个应用场景，帮助你同时提升：

- 应用数量（多 Agent 场景覆盖）
- 调用频次（可拆分独立运行）
- token 消耗（可被平台统计）

## 1) 快速开始

在 Git 仓库根目录执行：

```bash
python agent.py --app all --base main --head HEAD
```

分析最近一次提交：

```bash
python agent.py --app all --base HEAD~1 --head HEAD
```

分应用执行（便于单独统计）：

```bash
python agent.py --app docs --base main --head HEAD
python agent.py --app review --base main --head HEAD
python agent.py --app release --base main --head HEAD
python agent.py --app onboarding --base main --head HEAD
python agent.py --app qa --base main --head HEAD
```

## 2) 参数说明

- `--app`：应用类型，支持 `docs|review|release|onboarding|qa|all`（默认 `all`）
- `--repo`：仓库路径，默认 `.`
- `--base`：对比起点，默认 `main`
- `--head`：对比终点，默认 `HEAD`
- `--output`：输出目录，默认 `docs/agent`
- `--log-file`：运行指标日志文件（JSONL），默认 `docs/agent/usage_metrics.jsonl`

示例：

```bash
python agent.py --app review --repo . --base develop --head feature/abc --output docs/knowledge
python agent.py --app all --base main --head HEAD --log-file docs/agent/usage_metrics.jsonl
```

日志每次追加 1 行 JSON，包含：时间、应用类型、变更文件数、API 变更数、产物数量与产物路径，可直接用于申请材料统计。

## 3) 应用与产物清单

默认输出到 `docs/agent`：

- `docs` 应用：
  - `technical_changes.md`
  - `api_changes.md`
  - `faq.md`
  - `knowledge_base.json`
- `review` 应用：
  - `pr_review.md`
- `release` 应用：
  - `release_notes.md`
- `onboarding` 应用：
  - `onboarding.md`
- `qa` 应用：
  - `qa_pairs.json`

## 4) Token 申请用指标模板

你可以把以下表格按“天/周”记录，作为申请材料附件。

```text
[多应用 Agent 运行记录]
统计周期：YYYY-MM-DD ~ YYYY-MM-DD
仓库数量：X
团队人数：X

1) 应用覆盖
- docs:       调用 X 次
- review:     调用 X 次
- release:    调用 X 次
- onboarding: 调用 X 次
- qa:         调用 X 次
- all:        调用 X 次

2) 产物规模
- technical_changes.md 生成 X 份
- api_changes.md       生成 X 份
- faq.md               生成 X 份
- knowledge_base.json  生成 X 份
- pr_review.md         生成 X 份
- release_notes.md     生成 X 份
- onboarding.md        生成 X 份
- qa_pairs.json        生成 X 份

3) 效率收益
- PR 首轮通过率：由 A% -> B%
- 平均评审耗时：由 A 小时 -> B 小时
- 交付周期：由 A 天 -> B 天
- 新人上手周期：由 A 天 -> B 天

4) Token 使用
- 周总 token：X
- 单次平均 token：X
- 峰值日 token：X
- 与改造前对比：+X%
```

## 5) 可直接粘贴的申请文案示例

我们已将单一文档生成能力升级为多应用 Agent 套件，覆盖代码文档同步、PR 评审、发布说明、新人引导和知识问答等 5 类核心场景。各应用共享同一套变更分析与知识索引能力，并可按场景独立运行，形成稳定且可追踪的高频调用。随着应用覆盖扩大和团队接入增加，token 使用规模与业务产出同步增长。

## 6) 典型接入流程

1. 开发完成后触发 `agent.py`（建议先 `--app all`）  
2. 将产物归档到 CI artifact 或文档仓库  
3. 在 PR 模板中引用 `pr_review.md` 和 `release_notes.md`  
4. 将 `knowledge_base.json` / `qa_pairs.json` 接入内部检索或问答系统  

## 7) 后续增强建议

- 对接大模型生成更高质量摘要与 FAQ
- 增加 AST 级 API 变更识别，降低误报
- 为每个应用增加调用日志和 token 统计导出
- 对接飞书/Slack/Confluence 自动分发
