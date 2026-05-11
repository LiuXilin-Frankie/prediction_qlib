# Qlib BTCUSDT 5分钟事件合约 Baseline

## 目标

用最短路径验证一件事：只用 `Qlib` 内置因子，能否在 `BTCUSDT` 的 `5分钟` 事件合约场景中做出正期望方向策略。

## 实验设计

- 数据：`1min` Binance Qlib 数据，只用 `BTCUSDT`
- 额外字段：已补充 `vwap = quote_volume / volume`
- 因子：`Alpha158`，包含 `VWAP` 相关默认因子
- 标签：`涨/跌` 二分类
- 平盘样本：训练删除，验证和测试保留并按亏损处理
- 决策时点：每 `5分钟` 一个样本
- 入场价格：`t+1 open`
- 结算价格：`t+6 open`
- 模型：`LightGBM binary`
- 损失函数：`binary logloss`
- 训练方式：`90d train + 7d valid + 7d test`，按 `7d` 滚动
- 交易规则：固定下注 `5 USD`，非重叠开仓
- 结算规则：赢 `+3.5`，输 `-5`

理论盈亏平衡胜率：

```text
58.82%
```

## 代码结构

- `data_handler.py`：自定义 `Alpha158` 数据处理器和未来 5 分钟标签
- `experiment.py`：滚动训练、阈值搜索、测试回测
- `train_walk_forward.py`：CLI 入口

## 已做实验

### 实验 1

- 配置：`LightGBM`，阈值搜索区间 `0.55 ~ 0.80`
- 输出目录：`outputs/baseline_90d_lightgbm`

结果：

- 窗口数：`97`
- 测试交易数：`3665`
- 总体胜率：`55.01%`
- 单笔平均收益：`-0.3244`
- 总收益：`-1189`
- 最大回撤：`1205.5`
- 最长连亏：`11`

结论：

- 交易过多，低质量信号太多
- 胜率显著低于 `58.82%`
- 当前 baseline 不可交易

### 实验 2

- 配置：阈值搜索下限提高到 `0.58`
- 输出目录：`outputs/baseline_90d_lightgbm_t058`

结果：

- 测试交易数：`2078`
- 总体胜率：`55.68%`
- 单笔平均收益：`-0.2673`
- 总收益：`-555.5`
- 最大回撤：`674.0`
- 最长连亏：`9`

结论：

- 提高阈值后，交易数下降，亏损明显收敛
- 但胜率仍未达到盈亏平衡要求

### 实验 3

- 配置：阈值搜索下限提高到 `0.60`
- 输出目录：`outputs/baseline_90d_lightgbm_t060`

结果：

- 测试交易数：`561`
- 总体胜率：`55.61%`
- 单笔平均收益：`-0.2727`
- 总收益：`-153.0`
- 最大回撤：`207.5`
- 最长连亏：`6`

结论：

- 风险指标进一步改善
- 但胜率没有继续明显提升
- 当前模型只能通过“少做单”减少亏损，不能扭转成正期望

## 这次试验暴露的问题

- `Alpha158 + VWAP` 有一定方向信息，但边际不够
- 阈值提高能减少低质量交易，但不能单独解决负期望
- 窗口间表现不稳定，regime 依赖明显
- 很多窗口 `early stop` 很早，这不表示训练不充分，更像是可学习信号本来就弱
- `best_iteration` 与测试收益为负相关，与交易数为正相关，说明训练更久通常带来更多交易，但不带来更好收益
- 验证集选出的阈值对下一段测试集迁移不稳定

## 当前结论

当前 baseline 可以得出 3 个结论：

1. 只靠内置 `Alpha158`，很难稳定覆盖事件合约的 payout
2. 提高阈值是对的，但作用主要是降噪，不是创造 edge
3. 当前版本不具备实盘可用性

## 下一步

下一轮不优先“让模型训练更久”，而优先增强信号：

- 加入 `count`
- 加入 `quote_volume`
- 加入 `taker_buy_volume`
- 加入 `taker_buy_quote_volume`
- 默认阈值搜索区间改为 `0.58 ~ 0.80`

## 运行方式

先确保 `Qlib` 数据已包含 `vwap`：

```bash
python a6_customizations/binance_data-qlib/convert_binance_zip_to_qlib.py \
  --csv_dir a6_customizations/binance_data-qlib/csv_data_1min \
  --qlib_dir a6_customizations/binance_data-qlib/qlib_data_1min \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT \
  --freq 1min \
  --reuse_existing_parquet
```

说明：

- 这里使用的是正式 6-symbol `qlib_data_1min` 共享底层数据。
- baseline 训练本身仍然只交易 `BTCUSDT`，但不要用局部 `--symbols BTCUSDT` 去覆盖正式 `qlib_data_1min`。

正式 baseline 命令：

```bash
python a6_customizations/qlib_btc_5min_baseline/train_walk_forward.py \
  --model-type lightgbm \
  --train-days 90 \
  --valid-days 7 \
  --test-days 7 \
  --retrain-days 7 \
  --output-dir a6_customizations/qlib_btc_5min_baseline/outputs/baseline_90d_lightgbm
```

说明：

- 训练入口会自动预加载系统 `libstdc++.so.6`，修复本地 `LightGBM` 运行时依赖问题
- 输出目录包含 `summary.json`、`window_metrics.csv`、`trade_log.csv`
- 仓库默认只跟踪 `summary.json`、`config.json` 以及必要的 comparison JSON；`trade_log.csv`、`window_metrics.csv` 视为本地明细产物

## 实验对比结论表（更新）

下表汇总了近期关键实验，包含 `Alpha158`、`Alpha158 + factor_plan_tech_v1 + factor_plan_tech_close5m_short_v1`、训练窗口变化（`90d/60d`）以及“训练集低振幅随机删样”测试。

> 说明：删样仅作用于训练集，不影响验证和测试集。

| 因子配置 | 测试集窗口 | 是否删样 | total_pnl | avg_pnl | win_rate | max_dd | 最大连亏 | 对 baseline(total_pnl=-1189) |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| Alpha158 | 90d | 否 | -1189.0 | -0.3244 | 0.5501 | 1205.5 | 11 | 0 |
| Alpha158 | 60d | 否 | -835.5 | -0.3497 | 0.5471 | 884.0 | 9 | +353.5 |
| Alpha158 | 90d | 是（q40_drop50） | -1526.5 | -0.3635 | 0.5455 | 1585.5 | 7 | -337.5 |
| Alpha158 + factor_plan_tech_v1 + factor_plan_tech_close5m_short_v1 | 90d | 否 | -1072.5 | -0.3076 | 0.5521 | 1185.5 | 10 | +116.5 |
| Alpha158 + factor_plan_tech_v1 + factor_plan_tech_close5m_short_v1 | 60d | 否 | **-596.0** | **-0.2159** | **0.5628** | **657.5** | **7** | **+593.0** |
| Alpha158 + factor_plan_tech_v1 + factor_plan_tech_close5m_short_v1 | 90d | 是（q40_drop50） | -833.0 | -0.2917 | 0.5539 | 878.0 | 10 | +356.0 |
| Alpha158 + factor_plan_tech_v1 + factor_plan_tech_close5m_short_v1 | 60d | 是（q40_drop50） | -986.0 | -0.3537 | 0.5466 | 1012.5 | 9 | +203.0 |

当前最优配置为：`Alpha158 + factor_plan_tech_v1 + factor_plan_tech_close5m_short_v1 + 60d`。
