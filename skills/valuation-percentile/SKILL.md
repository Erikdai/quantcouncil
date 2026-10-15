---
name: valuation-percentile
description: A股估值分位与比较方法。Use when judging whether an A-share is cheap or expensive from PE/PB history, its own percentile, sell-side EPS forecasts and PEG.
---

# 估值分位与比较

## 核心指标
- **PE(TTM)**：滚动四季归母净利润。亏损公司 PE 为负，改用 PB 或 PS。
- **PB**：金融、周期、重资产行业优先看 PB；轻资产消费、科技看 PE。
- **PEG** = PE / 未来两年净利润复合增速(%)；< 1 偏便宜，> 2 偏贵。增速取卖方一致预期，需注明样本数。

## 历史分位法
1. 取近 3 年（或 5 年）每日 PE(TTM)，剔除负值。
2. 当前值所处分位：< 20% 低估区，20–80% 合理区，> 80% 高估区。
3. 分位只说明相对自身历史，行业逻辑变化（如增速中枢下移）时历史分位会失效，必须说明。

## 前瞻估值
- 前瞻 PE = 当前股价 / 卖方一致预期 EPS（当年、下一年）。
- 一致预期下修中的"低估值"可能是价值陷阱：比较最近 30 天与 90 天的预测均值变化。

## 输出格式
| 指标 | 当前值 | 3 年分位 / 参照 | 解读 |
最后一句给出：低估 / 合理 / 高估，以及最大的估值风险。
