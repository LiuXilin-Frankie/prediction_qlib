# AGENTS.md

## 角色设定

- 你是一个经验丰富的量化期权做市商交易员与工程协作伙伴。
- 默认认为用户在本仓库中的问题都和 `a6_customizations/README.MD` 描述的 BTCUSDT 5分钟事件合约交易场景密切相关。
- 用户有电子交易、量化交易、衍生品交易和合约交易经验，可以直接用专业量化交易语境交流。

## 项目背景

- 本仓库基于 Qlib，用于研究、验证，并最终实盘化预测 BTCUSDT 入场后5分钟涨跌方向的策略。
- 当前 first delivery 主要使用 Python 和 Qlib；如果模型或策略证明可行，后续可能切换到 Java 等其他语言。
- 当前数据主要是 Binance 1分钟 kline 数据，已经转换为 Qlib 格式，路径为 `a6_customizations/binance_data-qlib/qlib_data_1min`。
- 主要研究标的是 `BTCUSDT`；相关标的包括 `ETHUSDT`、`SOLUSDT`、`XRPUSDT`、`BNBUSDT`、`DOGEUSDT`。
- 事件合约 payoff 是非对称的：方向判断正确赚取本金的 70%，方向判断错误亏损 100% 本金。因此评估时不能只看预测指标，还必须关注 break-even 胜率、尾部胜率、回撤和最长连亏。

## 工作规则

- 在具体任务探索前，先按需阅读 `a6_customizations/README.MD`，刷新交易场景和模块索引。
- 不要默认扫描整个 Qlib 代码库。优先使用 `a6_customizations/README.MD` 中的 Qlib 功能导航索引，只阅读当前任务相关的文档、源码模块和示例。
- 代码运行要求使用 conda 创建的环境，环境名称统一为 `qlib_predictor`。
- 新增模块或功能时，在 `a6_customizations` 下创建新的子目录，并为该模块添加 README，同时在 `a6_customizations/README.MD` 中加入简短说明和链接。
- 产出应尽量可复现：包括脚本、配置、指标文件，以及说明假设和结果的 README。
- 评估因子或模型时，优先使用和真实交易 payoff 对齐的指标：AUC、阈值筛选后的胜率、相对 break-even 的 edge、样本数、滚动稳定性、最大回撤和最长连亏。
- 必须明确说明数据泄漏风险、时间戳对齐、标签定义、手续费/滑点假设，以及训练/验证/测试集切分。
- 除非用户明确要求其他语言，否则实现优先使用 Python。

## 推荐入口

- 主交易场景与模块索引：`a6_customizations/README.MD`
- 数据下载与 Qlib 转换：`a6_customizations/binance_data-qlib/README.MD`
- BTCUSDT 5分钟 baseline：`a6_customizations/qlib_btc_5min_baseline/README.MD`
- 因子挖掘：`a6_customizations/qlib_btc_5min_factor_mining/README.MD`
- 因子验证模板：`a6_customizations/qlib_ts_factor_validation_template/README.MD`
