# Qlib 时序因子验证模板（事件合约版）

## 目标

给单标的、短周期、事件合约场景提供一套“时序优先”的因子验证模板，避免直接套用横截面 IC 流程带来的失真。

默认适配：

- 交易定义：`t+1 open` 入场，`t+6 open` 结算
- 核心门槛：盈亏平衡胜率 `58.82%`
- 核心问题：高置信度样本是否具备正期望，且在滚动窗口内是否稳定

## 输入与输出

输入文件：

- `factor_panel.parquet`：来自因子挖掘模块（含 `datetime`、`target`、因子列）
- `factor_rankings.csv`（可选）：先验排序结果，用于挑选 top-k 因子
- `factor_rankings_by_instrument.csv`（可选）：逐标的排序结果

输出文件：

- `ts_factor_validation_summary_all.csv`：ALL（全部标的混合）摘要
- `ts_factor_validation_rolling_all.csv`：ALL 的滚动验证明细
- `ts_factor_validation_summary_by_instrument.csv`：逐标的摘要
- `ts_factor_validation_rolling_by_instrument.csv`：逐标的滚动明细
- `ts_factor_validation_summary.csv` / `ts_factor_validation_rolling.csv`：兼容旧接口（等价于 ALL）
- `summary.json`：运行配置和 top10 概览

## 验证指标（时序友好）

- `auc_best`：自动选择因子方向（`factor` 或 `-factor`）后的 AUC
- `best_tail_winrate`：上下尾分位（默认20%）中最佳一侧胜率
- `edge_vs_break_even`：`best_tail_winrate - 0.5882`
- `expected_pnl_per_trade`：按 `+3.5/-5` 赔率计算的单笔期望
- `longest_losing_streak`：最佳侧信号序列的最长连亏
- `rolling_edge_mean/p10/positive_ratio`：滚动窗口稳定性指标

## 运行方式

示例：验证挖掘后的 top30 因子（多标的，输出 ALL + 单标的）

```bash
python a6_customizations/qlib_ts_factor_validation_template/scripts/validate_timeseries_factors.py \
  --factor-panel a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_all_unds_30d/factor_panel.parquet \
  --factor-rankings a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_all_unds_30d/factor_rankings.csv \
  --factor-rankings-by-instrument a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_all_unds_30d/factor_rankings_by_instrument.csv \
  --top-k 30 \
  --output-dir a6_customizations/qlib_ts_factor_validation_template/outputs/top30_all_unds
```

示例：验证全部因子

```bash
python a6_customizations/qlib_ts_factor_validation_template/scripts/validate_timeseries_factors.py \
  --factor-panel a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_all_unds_30d/factor_panel.parquet \
  --top-k 0 \
  --output-dir a6_customizations/qlib_ts_factor_validation_template/outputs/all_all_unds
```

## 与 Qlib 标准流程关系

- 本模板不是替代 Qlib 工作流，而是补上“单标的时序任务”在因子验证层的空缺
- 对单标的 BTC 5min 任务，优先用本模板筛选因子，再接入 baseline 的滚动训练和交易回测
