# qlib_predictor 环境配置

本模块维护项目统一的 Python/Conda 运行环境，用于跑通 `a6_customizations` 下的 BTCUSDT 5分钟事件合约研究链路。

## 环境目标

- 环境名称固定为 `qlib_predictor`
- 使用本仓库源码安装 Qlib，而不是额外安装 PyPI 上的 `pyqlib`
- 默认对正式 Binance/Qlib 数据执行 6-symbol contract 检查：`BTCUSDT`、`ETHUSDT`、`SOLUSDT`、`XRPUSDT`、`BNBUSDT`、`DOGEUSDT`
- 覆盖当前自定义子模块：
  - `binance_data-qlib`
  - `qlib_btc_5min_baseline`
  - `qlib_btc_5min_factor_mining`
  - `qlib_ts_factor_validation_template`

## 一键创建或更新

在仓库根目录运行：

```bash
bash a6_customizations/qlib_predictor_environment/setup_env.sh
```

脚本会执行：

1. 按 `a6_customizations/environment.yml` 创建或更新 `qlib_predictor`
2. 用 editable 模式安装当前 Qlib 源码树
3. 运行环境 smoke test

## 手工命令

如果不使用脚本，可以手工执行：

```bash
conda env create -f a6_customizations/environment.yml
conda run -n qlib_predictor python -m pip install --no-build-isolation -e .
conda run -n qlib_predictor python a6_customizations/qlib_predictor_environment/smoke_test_environment.py
```

如果环境已存在，用更新命令：

```bash
conda env update -n qlib_predictor -f a6_customizations/environment.yml --prune
conda run -n qlib_predictor python -m pip install --no-build-isolation -e .
```

## 运行方式约定

之后所有项目命令都建议使用：

```bash
conda activate qlib_predictor
```

或直接用：

```bash
conda run -n qlib_predictor python ...
```

训练脚本如果遇到 macOS 下 Matplotlib 缓存目录不可写的 warning，可在命令前加：

```bash
MPLCONFIGDIR=/private/tmp/matplotlib-cache
```

## Smoke Test 覆盖范围

`smoke_test_environment.py` 不做耗时训练，但会做严格的数据契约检查：

- 核心依赖可导入：`numpy`、`pandas`、`pyarrow`、`lightgbm`、`xgboost`、`qlib`
- Qlib 可指向本地 1分钟数据目录初始化
- `source zip -> parquet -> qlib instruments/features/calendar` 四层保持一致
- 正式 `qlib_data_1min` 恰好覆盖固定 6-symbol universe
- Binance 数据脚本、baseline、因子挖掘、时序验证入口可导入
- 因子挖掘 `show-plan` 能渲染候选因子配置

如果缺 symbol、时间回退、`Parquet` 与 `instruments/all.txt` 不一致，smoke test 会直接失败。

它不是收益验证；真实策略仍需要通过各子模块 README 中的训练、挖掘、验证命令输出指标文件。

## 已知边界

`qlib_predictor` 面向本仓库 `a6_customizations` 的 Binance 数据、baseline 训练、因子挖掘和时序验证链路。Qlib 自带的部分可选 benchmark、RL、数据采集脚本依赖 `torch`、`tensorflow`、`catboost`、`tianshou`、`baostock`、`pycoingecko` 等额外包，且有些 requirements 钉在较旧版本；这些不属于当前统一环境的默认覆盖范围。
