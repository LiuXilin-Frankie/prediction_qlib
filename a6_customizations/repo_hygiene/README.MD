# repo_hygiene

本模块维护仓库提交治理规则，目标是在不影响 `notebook` 研究效率的前提下，尽量减少噪音提交和误上传生成型产物。

## 设计目标

- `notebook` 默认允许提交
- `.ipynb` 入库前自动清空 `output` 和 `execution_count`
- 阻止明显不该进入 Git 的生成型目录、缓存目录和明细结果文件
- 提供一个轻量自检入口，快速扫描当前仓库里是否有大文件或脏产物

## 组成

- `repo_hygiene.py`：核心 CLI，负责 `notebook` 清理、staged 校验和仓库扫描
- `setup_repo_hygiene.sh`：配置本地 Git filter，并安装 `pre-commit` hook

## 标准入口

如果你已经按项目约定运行：

```bash
bash a6_customizations/qlib_predictor_environment/setup_env.sh
```

则本模块会被自动配置，不需要额外手工操作。

如果只想单独重装仓库治理配置，可以运行：

```bash
bash a6_customizations/repo_hygiene/setup_repo_hygiene.sh
```

## 行为约定

### Notebook

- 工作区里的 `notebook` 仍然可以正常保留输出，方便研究
- Git 入库版本会经过 clean filter 自动去掉 `output` 与执行计数
- `pre-commit` 会校验 staged 进去的 `.ipynb` 是否已经是干净版本

### 数据与研究产物

默认不提交：

- `binance_data_1min/` 原始 zip
- `csv_data_1min*/` 中间 `Parquet`
- `qlib_data_1min/features/` Qlib 二进制特征
- `trade_log.csv`、`window_metrics.csv`
- `__pycache__`、`.ipynb_checkpoints/`、`.DS_Store`

默认允许提交：

- `manifests/**/*.json`
- `outputs/**/summary.json`
- `outputs/**/config.json`
- 必要的 comparison JSON
- `.ipynb` 文件本体

## 手工命令

清理一个或多个 `notebook`：

```bash
python a6_customizations/repo_hygiene/repo_hygiene.py strip-notebook path/to/file.ipynb
```

扫描当前仓库里是否有异常大文件或误跟踪的生成型文件：

```bash
python a6_customizations/repo_hygiene/repo_hygiene.py scan
```

如果你只是想看 staged 的 `notebook` 是否已经被正确清理，也可以运行：

```bash
python a6_customizations/repo_hygiene/repo_hygiene.py check-staged-notebooks a6_customizations/binance_data-qlib/data_get_try.ipynb
```
