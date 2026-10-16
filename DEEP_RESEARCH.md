# 问题驱动的专题投研

本版新增一个核心功能：围绕单家美股公司的具体研究问题，检索 SEC 原始财报、检查财务数据和反证，生成带可核查引文的研究报告。

## 使用

打开侧栏“专题投研”，输入 MSFT/AAPL 等美国本土公司的股票代码和研究问题。支持披露 10-K/10-Q 的公司，不支持 ETF、20-F 外国发行人或跨公司比较。资料截止日留空为今天；截止日是披露日期口径，不是盘中时间。

例题：
> 微软的 AI 资本开支是否正在转化为足够的收入和现金流？请区分已披露的事实、可计算的指标和目前无法证明的部分。

开始研究后可以查看研究问题拆解、资料收集与工具调用过程。刷新页面、关闭页面或重启 API 不会删除任务及报告。点击每条结论下的证据编号，可以查看逐字原文、SEC 链接、披露日期、原始文件哈希；计算证据可以逐层打开计算输入及原始事实。支持停止、重新研究和下载 Markdown 报告。

## 它与原有 Agent 的区别

原有流程围绕“这只股票怎么看”运行固定分析师与多空辩论。本功能从用户的问题出发，先规划需要核验的假设和证据，再检索资料、计算和回答，不输出买卖评级，也不接交易执行。

## 数据与计算

- SEC submissions：按披露日期选取最近两份 10-K 和两份 10-Q。原始 HTML 按 accession 缓存在现有共享数据目录，保留 SHA-256。
- SEC 全文：去除隐藏 iXBRL、脚本及样式，保留正文和表格文字，分片后用 Python 自带的 SQLite FTS5 搜索。查询由 Agent 用英文生成，报告可以为中文或英文。不需要新向量模型或嵌入服务。
- SEC companyfacts：读取截至截止日已披露的营收、经营利润、净利润、经营现金流、现金资本开支、现金、总资产、现金回购和现金分红。保留期间起止、披露日期、单位、原始 XBRL 标签与 accession；不把年度或 YTD 数值冒充单季。
- 代码计算：基于已读取的财务事实生成基础增长率和适用的同期比率、经营现金流减现金资本开支；Agent 还可主动调用计算工具。基数为零或负数的百分比增长、不同期间的比率均拒绝。现金资本开支不自动包含融资租赁，不把现金 FCF 代理指标解释成 AI 投资回报率。
- 未披露的 AI 收入/投入、分部数据和因果关系必须在结论中明确说明无法证明，不能用全公司或云业务增长代替。

## 完整性检查的边界

最终报告结构化为：问题回答、关键发现、反证与其他解释、未知项、改变观点的条件。每项发现标注事实或推断，并带至少一条引文。

程序检查来源 ID 是否真实取得、逐字引文是否存在于保存的证据中，以及结论中的数字是否出现在所引片段/日期元数据中。要求财务值使用工具给出的 USD million 原值，禁止模型自行换算单位或做舍入。现金 FCF 等推导指标还必须引用代码计算来源。对每份草稿另发起一次模型复核，检查单位、期间、引用含义与结论逻辑，覆盖未知项等未带引文的字段；模型复核仍可能出错。最多生成三份草稿，每份同时进行程序检查与模型复核，允许两次完整报告修复，修复前后的报告和错误都保存在 verification.attempts，仍不通过则状态为“需要复核”。年度财务序列只取年报，排除季报中的滚动十二个月数据。回购与分红取现金支付标签；代码可按同公司、同期间计算加减链，并保留未舍入的输入与原始证据。资产采购现金值与公司自定义的净资本开支可能不同，不混用。这不等于独立审计了所有推断、因果关系或每一个数字，重要判断仍需人工打开证据核对。没有取得任何全文时直接失败，不生成伪报告。

## 后台与持久化

使用现有 PostgreSQL、Redis/Taskiq 和模型设置。独立 research_jobs 表保存问题、模型配置（无密钥）、进度、证据快照、报告、缺失资料和检查结果。API 不执行长研究。

最多 16 次主动工具调用，整体 15 分钟超时；停止操作阻止后续步骤，已经发出的模型请求可能完成并计费。定时清理任务将 30 分钟没有进展的任务标记为失败，可重新研究。重试创建新记录，保留原任务，避免覆盖历史。

## 启动

完整 Docker 部署继续使用原 README 的 `docker compose up -d --build`，包含数据库、队列、MCP、API、worker、scheduler 和前端。数据库启动时执行 Alembic 新增表结构。模型 API key 可在设置中配置或沿用环境变量，建议设置 `SEC_EDGAR_USER_AGENT` 为自己的请求身份。

本机已安装依赖后，可用 `bash scripts/run_research_local.sh` 一次启动；Ctrl-C 停止应用进程，数据库数据保留。也可以分终端启动：

```bash
docker compose -p quantcouncil up -d postgres redis
.venv/bin/alembic upgrade head
.venv/bin/python -m quantcouncil.mcp_server --transport streamable-http --port 8019
.venv/bin/uvicorn quantcouncil.api.main:app --host 127.0.0.1 --port 8018
.venv/bin/taskiq worker quantcouncil.worker.broker:broker quantcouncil.worker.tasks --workers 1 --max-async-tasks 2
.venv/bin/taskiq scheduler quantcouncil.worker.broker:scheduler quantcouncil.worker.tasks
VITE_API_TARGET=http://127.0.0.1:8018 npm run dev --prefix frontend -- --host 127.0.0.1 --port 5187 --strictPort
```

MCP/API/worker/scheduler/前端各自在一个终端运行。本地 `.env` 的 MCP 地址应为 `QUANTCOUNCIL_MCP_URL=http://127.0.0.1:8019/mcp`。

## 接口

- POST /api/deep-research：创建任务，输入 ticker/question/as_of/language。
- GET /api/deep-research：历史记录。
- GET /api/deep-research/{id}：状态、进度、原始证据、报告与检查。
- POST /api/deep-research/{id}/cancel：停止后续研究步骤。
- POST /api/deep-research/{id}/retry：重新研究并创建新记录。
- GET /api/deep-research/{id}/report.md：下载报告及被引用的证据和计算输入。

## 官方资料

- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://www.sec.gov/about/developer-resources
- https://www.sqlite.org/fts5.html

真实测试结果与限制见 [DEEP_RESEARCH_VALIDATION.md](DEEP_RESEARCH_VALIDATION.md)。

模型结构化输出采用供应商支持的协议，保留最终原文、结束原因和用量；格式不合法时仅纠正一次，仍失败则明确失败。600 字证据重叠覆盖引用上限；只对表格空单元格/美元符号的布局差异和同一文件的相邻片段恢复逐字原文，不允许跳行、换公司或换文件来凑引文。计算证据用简短公式和输入 ID，Markdown 导出递归包含整条输入链。

“模型对回答的证据判断”评价回答本身是否有依据；有充分证据的否定回答也可为 supported。证据收集阶段结束后才生成报告，避免重复撰写。使用 DeepSeek 原生 V4/Flash 时，仅结构化报告写作使用 low reasoning effort；调查和单独复核保留所配置深度。超时仍明确失败，不自动换模型。
