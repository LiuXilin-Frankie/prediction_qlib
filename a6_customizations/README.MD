# 基于Qlib的预测库

这个项目的目的是预测BTCUSDT五分钟之后的涨跌并进行交易。目前的想法是基于Qlib的框架进行，因为它内置很多因子方法。现实中我是一名量化期权做市商交易员，所以我有丰富的电子交易，量化交易，合约交易的经验。我们可以直接在专业的角度下交流。

交易的规则如下
+ 任意时刻我可以交易事件合约买比特币5分钟后（其实有其它时间可选，但是第一阶段我想专注于五分钟）的涨或者跌，买入的金额最低是5美刀，最高是25美刀。
+ 假如我买入5美刀涨，如果5分钟后合约价格相比我买入时上涨了（无论涨多少都可以），我就可以赚取3.5美刀，也就是70%的收益率；如果5分钟后合约价格相比我买入时下跌了（无论跌多少都可以），我就亏损5美刀，也就是100%的亏损率。
+ 如果我买跌也是一样，我只能在5分钟后价格真的下跌的情况下获利，其他的情况我都会损失本金。事件合约只在意我买入的事件是否发生，跟涨跌幅度无关。
+ 真正的交易过程中，即使长期看我的胜率很高，赢和亏出现的顺序也很重要，我想要尽量避免长时间连续的亏损，这会迅速消耗掉我所有的资金导致我无法继续交易。

数据详情：
+ 我在“a6_customizations/binance_data-qlib/qlib_data_1min”路径下存储了每分钟的价格数据，并且转化为了qlib对应的数据格式。“a6_customizations/binance_data-qlib”下有他们的获取代码；
+ 除了BTCUSDT的价格意外，我还下载了'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT'的数据，不过目前以BTCUSDT为主进行测试；
+ 数据每列的含义如下：
    + open: 该分钟的开盘价
    + high: 该分钟的最高价
    + low: 该分钟的最低价
    + close: 该分钟的收盘价
    + volume: 该分钟的交易量
    + count: 该分钟的交易笔数
    + quote_volume: 该分钟的成交额
    + taker_buy_base_volume: 该分钟的主动买入成交量
    + taker_buy_quote_volume: 该分钟的主动买入成交额
    + factor: 主要是用来计算复利的因子，对数字货币不适用，请你忽略
+ 目前只有这些数据，如果需要更高频的数据也可以进一步获取，数据的获取路径是“https://data.binance.vision/?prefix=data/futures/um/daily/”，该页面下有 1.aggTrades, 2.bookDepth, 3.bookTicker, 4.indexPriceKlines, 5.klines, 6.markPriceKlines, 7.metrics, 8.premiumIndexKlines, 9.trades. 目前我是用的主要是klines的数据，这些数据最为经典，我希望你能先利用这些数据有一个不错的 first delivery， 后续我们再考虑如何提升。

项目要求：
+ 项目目前基于qlib的框架进行
+ 代码运行要求使用conda创建的环境，环境名称统一为 `qlib_predictor`
+ 每当进行一个新的模块/添加功能。请你把新的代码添加到“a6_customizations”路径下，创建一个新的文件夹。并在文件夹中创建对应的readme进行说明。这里添加一段简单的说明并且链接到对应的readme详细说明中。


## 项目结构

项目被重构为模块化设计，分为以下几个主要组件：

```
└── prediction_qlib/        # 开源项目 qlib 的源码以及个人添加的一些代码
    ├── a6_customizations   # lxl自定义的一些文件，主要包含环境配置，说明文件等等
    └── others              # 其它qlib下的文件

```

### a6_customizations 模块文档索引

按照本项目约定：每个新模块放在 `a6_customizations` 下独立目录，并提供对应 README。

- `qlib_predictor_environment`：统一的 `qlib_predictor` Conda 环境、editable 安装脚本与各子模块 smoke test  
  详细文档见：[a6_customizations/qlib_predictor_environment/README.MD](./qlib_predictor_environment/README.MD)

- `binance_data-qlib`：Binance 1分钟数据下载、校验、转换为Qlib数据格式，现已标准化为 `config + CLI + manifest + contract check` 的流水线  
  详细文档见：[a6_customizations/binance_data-qlib/README.MD](./binance_data-qlib/README.MD)

- `qlib_btc_5min_baseline`：使用Qlib内置 `Alpha158` 因子与 `LightGBM`，对 `BTCUSDT` 的 `5分钟` 事件合约进行滚动训练、阈值筛选与测试集交易模拟的 baseline 方案  
  详细文档见：[a6_customizations/qlib_btc_5min_baseline/README.MD](./qlib_btc_5min_baseline/README.MD)

- `qlib_btc_5min_factor_mining`：面向 `t+1 open -> t+6 open` 事件目标的增量因子挖掘子项目；先进行候选因子与参数确认，再执行正式挖掘与训练对比  
  详细文档见：[a6_customizations/qlib_btc_5min_factor_mining/README.MD](./qlib_btc_5min_factor_mining/README.MD)

- `qlib_ts_factor_validation_template`：面向单标的时序任务的通用因子验证模板，输出 `AUC`、尾部胜率、`edge_vs_break_even`、滚动稳定性和最长连亏等指标  
  详细文档见：[a6_customizations/qlib_ts_factor_validation_template/README.MD](./qlib_ts_factor_validation_template/README.MD)



## Qlib 功能导航索引（文档 / 函数 / 代码 / 示例 一一对应）

这个索引的目标是让后续 AI 任务可以“按功能直达”，避免每次扫描全量仓库。  
使用方式：先定位“功能域”，再沿着“官方文档 -> 关键函数/类 -> 源码路径 -> 示例”快速落地。

### 1) 快速入口（安装、初始化、执行）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 安装与初始化 | `docs/start/installation.rst` `docs/start/initialization.rst` | `qlib.init` | `qlib/__init__.py` | `examples/workflow_by_code.py` |
| 数据下载（官方数据） | `docs/start/getdata.rst` | `GetData().qlib_data`（CLI） | `scripts/get_data.py` | `python scripts/get_data.py ...` |
| 一键工作流执行 | `docs/component/workflow.rst` | `workflow()` / `run()`（qrun 入口） | `qlib/workflow/cli.py` | `examples/benchmarks/*/workflow_config_*.yaml` |
| 配置实例化 | `docs/component/workflow.rst` | `init_instance_by_config` | `qlib/utils/mod.py` | `examples/workflow_by_code.py` |

### 2) 数据层（Data Layer）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 日历/股票池/特征获取 API | `docs/component/data.rst` `docs/start/getdata.rst` | `qlib.data.D.calendar` `D.instruments` `D.list_instruments` `D.features` | `qlib/data/data.py` | `docs/start/getdata.rst` 代码片段 |
| 表达式与基础特征 | `docs/component/data.rst` `docs/advanced/alpha.rst` | `Feature` `ExpressionOps` | `qlib/data/base.py` | `docs/start/getdata.rst` 表达式示例 |
| 股票池过滤 | `docs/component/data.rst` | `NameDFilter` `ExpressionDFilter` | `qlib/data/filter.py` | `docs/start/getdata.rst` 过滤示例 |
| DataLoader | `docs/component/data.rst` | `QlibDataLoader` `StaticDataLoader` | `qlib/data/dataset/loader.py` | `docs/advanced/alpha.rst` |
| DataHandler 与预处理 | `docs/component/data.rst` | `DataHandlerLP`（含 Processor 体系） | `qlib/data/dataset/handler.py` `qlib/data/dataset/processor.py` | `qlib.contrib.data.handler.Alpha158` |
| Dataset 抽象 | `docs/component/data.rst` | `DatasetH` | `qlib/data/dataset/__init__.py` | `examples/highfreq/workflow.py` |
| 缓存机制 | `docs/component/data.rst` | `MemCache` `ExpressionCache` `DatasetCache` | `qlib/data/cache.py` | `examples/data_demo/*` |
| 本地存储抽象 | `docs/reference/api.rst` | `FileCalendarStorage` `FileInstrumentStorage` `FileFeatureStorage` | `qlib/data/storage/file_storage.py` | - |

### 3) 因子工程（公式因子 / Alpha）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 公式因子构建 | `docs/advanced/alpha.rst` | `QlibDataLoader(config=...)` + 表达式算子 | `qlib/data/dataset/loader.py` `qlib/data/ops.py` | `docs/advanced/alpha.rst` 的 MACD 示例 |
| 内置因子集 | `docs/component/data.rst` | `Alpha158` `Alpha360` | `qlib/contrib/data/handler.py` | `examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml` |
| 自定义数据转 bin | `docs/component/data.rst` | `dump_all`（脚本入口） | `scripts/dump_bin.py` | `scripts/check_data_health.py` |

### 4) 预测模型（训练 / 预测 / 集成）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 模型基类 | `docs/component/model.rst` `docs/reference/api.rst` | `Model` `ModelFT` | `qlib/model/base.py` | `docs/start/integration.rst` |
| LightGBM 基线 | `docs/component/model.rst` | `LGBModel` | `qlib/contrib/model/gbdt.py` | `examples/benchmarks/LightGBM/` |
| 其他 contrib 模型 | `docs/component/model.rst` | `pytorch_*` `xgboost` `catboost` 等 | `qlib/contrib/model/` | `examples/benchmarks/` |
| 自定义模型接入 | `docs/start/integration.rst` | 约定实现 `__init__/fit/predict/(finetune)` | 继承 `qlib.model.base.Model` | `examples/workflow_by_code.ipynb` |

### 5) 策略与回测（组合管理）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 策略抽象与 TopkDrop | `docs/component/strategy.rst` | `TopkDropoutStrategy` `WeightStrategyBase` `EnhancedIndexingStrategy` | `qlib/contrib/strategy/signal_strategy.py` | `examples/portfolio/` |
| 规则策略 | `docs/component/strategy.rst` | `TWAPStrategy` 等 | `qlib/contrib/strategy/rule_strategy.py` | `examples/rl_order_execution/` |
| 回测核心 | `docs/component/strategy.rst` | `backtest` | `qlib/backtest/__init__.py` | `examples/workflow_by_code.py` |
| 日频便捷回测与风险分析 | `docs/component/strategy.rst` | `backtest_daily` `risk_analysis` | `qlib/contrib/evaluate.py` | `docs/component/strategy.rst` 示例 |

### 6) 结果分析与可视化（Report）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 持仓/收益/风险图 | `docs/component/report.rst` | `analysis_position.report/score_ic/risk_analysis` | `qlib/contrib/report/analysis_position/` | `docs/component/report.rst` |
| 模型分组表现图 | `docs/component/report.rst` | `analysis_model_performance` | `qlib/contrib/report/analysis_model/analysis_model_performance.py` | 同上 |
| Alpha 评估工具 | `docs/reference/api.rst` | `calc_ic` `calc_long_short_return` | `qlib/contrib/eva/alpha.py` | `docs/component/recorder.rst` |

### 7) 工作流与实验管理（Workflow / Recorder）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 研究工作流编排 | `docs/component/workflow.rst` | `qrun`(CLI) / `R.start` | `qlib/workflow/cli.py` `qlib/workflow/__init__.py` | `examples/workflow_by_code.py` |
| 实验与记录器 | `docs/component/recorder.rst` | `QlibRecorder` `ExpManager` `Experiment` `Recorder` | `qlib/workflow/__init__.py` `qlib/workflow/expm.py` `qlib/workflow/exp.py` `qlib/workflow/recorder.py` | `mlflow ui` + 实验目录 |
| 记录模板 | `docs/component/recorder.rst` | `SignalRecord` `SigAnaRecord` `PortAnaRecord` | `qlib/workflow/record_temp.py` | `docs/component/workflow.rst` task.record |
| MLflow 管理器 | `docs/component/recorder.rst` | `MLflowExpManager` | `qlib/workflow/expm.py` | - |

### 8) 在线服务（Online Serving）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 在线管理器 | `docs/component/online.rst` | `OnlineManager` | `qlib/workflow/online/manager.py` | `examples/online_srv/rolling_online_management.py` |
| 在线策略与更新 | `docs/component/online.rst` | `qlib.workflow.online.strategy` `RecordUpdater` | `qlib/workflow/online/strategy.py` `qlib/workflow/online/update.py` | `examples/online_srv/update_online_pred.py` |
| 在线工具 | `docs/component/online.rst` | `qlib.workflow.online.utils` | `qlib/workflow/online/utils.py` | `examples/online_srv/online_management_simulate.py` |

### 9) 高频与嵌套决策执行（NDE）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 嵌套执行框架 | `docs/component/highfreq.rst` | 组合 `strategy + executor + backtest` | `qlib/backtest/` `qlib/contrib/strategy/` | `examples/nested_decision_execution/workflow.py` |
| 高频数据与处理 | `docs/component/highfreq.rst` | 高频处理器与 provider | `qlib/contrib/data/highfreq_handler.py` `qlib/contrib/data/highfreq_provider.py` | `examples/highfreq/` `examples/orderbook_data/` |

### 10) 元学习（Meta Controller）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| MetaTask / MetaDataset | `docs/component/meta.rst` | `MetaTask` `MetaTaskDataset` | `qlib/model/meta/task.py` `qlib/model/meta/dataset.py` | `examples/benchmarks_dynamic/DDG-DA/` |
| MetaModel 体系 | `docs/component/meta.rst` | `MetaModel` `MetaTaskModel` `MetaGuideModel` | `qlib/model/meta/model.py` | 同上 |

### 11) 强化学习（QlibRL）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| RL 总览与快速开始 | `docs/component/rl/overall.rst` `docs/component/rl/quickstart.rst` | `train_onpolicy` `backtest`（CLI） | `qlib/rl/contrib/train_onpolicy.py` `qlib/rl/contrib/backtest.py` | `examples/rl_order_execution/` |
| 订单执行环境 | `docs/component/rl/quickstart.rst` | `SingleAssetOrderExecution` `SingleAssetOrderExecutionSimple` | `qlib/rl/order_execution/simulator_qlib.py` `qlib/rl/order_execution/simulator_simple.py` | `examples/rl_order_execution/exp_configs/` |
| 状态/动作解释器 | `docs/component/rl/quickstart.rst` | `FullHistoryStateInterpreter` `CategoricalActionInterpreter` | `qlib/rl/order_execution/interpreter.py` | 同上 |
| 策略网络与奖励 | `docs/component/rl/quickstart.rst` | `PPO` `PAPenaltyReward` | `qlib/rl/order_execution/policy.py` `qlib/rl/order_execution/reward.py` | 同上 |

### 12) 任务管理（滚动训练 / 自动收集）

| 功能域 | 官方文档 | 关键函数 / 类（模块路径） | 源码位置 | 示例 / 脚本 |
|---|---|---|---|---|
| 任务生成 | `docs/advanced/task_management.rst` | `TaskGen` `RollingGen` | `qlib/workflow/task/gen.py` | `examples/model_rolling/task_manager_rolling.py` |
| 任务调度与执行 | `docs/advanced/task_management.rst` | `TaskManager` `run_task` | `qlib/workflow/task/manage.py` | 同上 |
| 训练器 | `docs/advanced/task_management.rst` | `task_train` `TrainerR` `TrainerRM` | `qlib/model/trainer.py` | 同上 |
| 结果收集与集成 | `docs/advanced/task_management.rst` | `RecorderCollector` `Group` `Ensemble` | `qlib/workflow/task/collect.py` `qlib/model/ens/` | 同上 |

### 13) 与本项目（BTCUSDT 5min 事件合约）最相关的推荐阅读顺序

1. `docs/component/data.rst`（数据与特征全链路）  
2. `docs/advanced/alpha.rst`（公式因子构建）  
3. `docs/component/model.rst`（模型训练与预测）  
4. `docs/component/strategy.rst`（信号转交易决策与回测）  
5. `docs/component/report.rst`（评价指标和图形分析）  
6. `docs/component/workflow.rst` + `docs/component/recorder.rst`（可复现实验管理）  

### 14) 你后续给 AI 任务时可直接引用的模板

```text
目标功能域: [例如 数据层/策略回测/RL订单执行]
优先文档: [docs/...]
优先源码: [qlib/...]
优先示例: [examples/...]
限制条件: [例如 只使用1min币圈数据、标签定义、手续费与滑点设定]
产出要求: [代码路径 + 结果指标 + 下一步迭代建议]
```
