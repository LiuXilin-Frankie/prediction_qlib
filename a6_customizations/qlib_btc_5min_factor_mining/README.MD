# Qlib BTCUSDT 5min 因子挖掘子项目

## 目标

在现有 `Alpha158` baseline 的基础上，构建一个可迭代的“增量因子挖掘”模块，优先服务以下交易目标：

- 预测任务：`t+1 open` 入场，`t+6 open` 结算（5分钟事件方向）
- 策略目标：提升高置信度样本胜率，尽量稳定超过盈亏平衡胜率 `58.82%`
- 风险目标：减少连续亏损段，避免回撤过深

## 当前状态

- 本模块已完成初始化（目录、配置、脚本骨架）
- 技术指标因子计划已确认（`factor_plan_tech_v1.yaml`）
- 已支持首版自动挖掘与单因子排名输出

## 目录结构

```text
qlib_btc_5min_factor_mining/
├── README.MD
├── configs/
│   └── factor_plan_tech_v1.yaml
├── scripts/
│   ├── build_factor_expressions.py
│   └── run_factor_mining.py
└── outputs/
```

## 因子设计原则（面向 5 分钟事件合约）

- 短周期优先：窗口集中在 `3/5/8/13/21/34/55`
- 方向性优先：先做“涨跌方向可分”的指标，再扩展复杂因子
- 概率稳定性优先：避免只提升交易次数而不提升胜率
- 参数保守：先上小而稳的参数网格，避免过度搜索导致过拟合

## 技术指标因子范围（v1）

当前使用 `configs/factor_plan_tech_v1.yaml`（已确认）进行挖掘。

候选族（v1）：

- 趋势/动量：`EMA gap`、`MACD`、`RSI`、`ROC`
- 波动率：`ATR`、`真实波动率`、`布林带带宽`
- 量价压力：`OBV`、`MFI`、`CMF`、`主动买比例`
- 微结构代理：`high-low range`、`close location value`、`k线实体/影线比`

## 使用方式

1) 查看候选计划：

```bash
python a6_customizations/qlib_btc_5min_factor_mining/scripts/run_factor_mining.py \
  --plan a6_customizations/qlib_btc_5min_factor_mining/configs/factor_plan_tech_v1.yaml \
  --mode show-plan
```

2) 执行技术指标因子挖掘（示例：最近30天，单标的）：

```bash
python a6_customizations/qlib_btc_5min_factor_mining/scripts/run_factor_mining.py \
  --plan a6_customizations/qlib_btc_5min_factor_mining/configs/factor_plan_tech_v1.yaml \
  --instrument BTCUSDT \
  --lookback-days 30 \
  --output-dir a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_30d \
  --mode mine
```

3) 执行多标的联合挖掘（`ALL`）：

```bash
python a6_customizations/qlib_btc_5min_factor_mining/scripts/run_factor_mining.py \
  --plan a6_customizations/qlib_btc_5min_factor_mining/configs/factor_plan_tech_v1.yaml \
  --instrument ALL \
  --lookback-days 30 \
  --output-dir a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_all_unds_30d \
  --mode mine
```

多标的输出说明：

- `factor_panel.parquet`：包含 `instrument` 列
- `factor_rankings.csv`：所有标的混合后的总体排名（ALL）
- `factor_rankings_by_instrument.csv`：逐标的排名

4) 对比自定义因子与 `Alpha158` 的因子回测效果：

```bash
python a6_customizations/qlib_btc_5min_factor_mining/scripts/compare_with_alpha158.py \
  --custom-factor-panel a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_all_unds_30d/factor_panel.parquet \
  --instrument ALL \
  --output-dir a6_customizations/qlib_btc_5min_factor_mining/outputs/compare_custom_vs_alpha158_all_unds_30d
```

对比输出说明：

- `factor_backtest_comparison_all.csv`：两类因子统一排名
- `factor_backtest_comparison_custom.csv`：仅自定义因子
- `factor_backtest_comparison_alpha158.csv`：仅 `Alpha158` 因子
- `source_summary.csv`：按因子来源的聚合对比

5) close-only 5min 短周期构建（`t, t-5, t-10...`）：

```bash
python a6_customizations/qlib_btc_5min_factor_mining/scripts/run_factor_mining.py \
  --plan a6_customizations/qlib_btc_5min_factor_mining/configs/factor_plan_tech_close5m_short_v1.yaml \
  --instrument ALL \
  --sample-minutes 5 \
  --entry-offset-minutes 1 \
  --horizon-minutes 1 \
  --lookback-days 30 \
  --output-dir a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_close5m_short_30d \
  --mode mine
```

说明：

- `feature_construction=close_5min_only` 时，技术指标仅基于采样后的 `close` 序列构建
- 参数只保留一组短周期配置（见 `factor_plan_tech_close5m_short_v1.yaml`）

## 下一步

- 把优选因子接入滚动训练，与 baseline 做逐窗对比
- 重点跟踪：`best_tail_winrate`、`edge_vs_break_even`、`最长连亏`
- 根据结果再做 v2 参数收缩与共线性去重
- 时序专项验证模板见：`a6_customizations/qlib_ts_factor_validation_template/README.MD`
