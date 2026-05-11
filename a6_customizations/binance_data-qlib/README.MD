# Binance 1分钟数据获取与Qlib转换

本模块用于从 Binance 公共数据源批量下载永续合约 K 线数据（1m），并转换为 Qlib 可直接使用的数据格式。

## 模块目标

- 从 `https://data.binance.vision` 下载按天打包的 1m K 线 zip 文件。
- 对每个下载文件做 SHA256 校验（使用 Binance 提供的 `.CHECKSUM`）。
- 将 zip 中原始数据整理为中间 Parquet。
- 将 Parquet 转储为 Qlib 二进制格式（`features/`、`calendars/`、`instruments/`）。

## 正式数据契约

本仓库正式维护固定 6-symbol universe：

- `BTCUSDT`
- `ETHUSDT`
- `SOLUSDT`
- `XRPUSDT`
- `BNBUSDT`
- `DOGEUSDT`

正式数据目录约定如下：

- `binance_data_1min/<symbol>/` 六个目录都存在
- `csv_data_1min/<symbol>.parquet` 六个文件都存在
- `qlib_data_1min/features/<symbol lower>/` 六个目录都存在
- `qlib_data_1min/instruments/all.txt` 恰好六行

如果只想做 `1~2` 个 symbol 的局部实验，必须显式写到独立的 `csv_dir` 和 `qlib_dir`，不能覆盖正式 `csv_data_1min` / `qlib_data_1min`。

## 目录结构

```text
binance_data-qlib/
├── binance_data_downloader.py         # 单文件下载+校验
├── binance_batch_downloader.py        # 按交易对/日期批量下载
├── data_contract.py                   # 6-symbol contract 与 manifest 公共逻辑
├── convert_binance_zip_to_qlib.py     # zip -> parquet -> qlib
├── run_data_pipeline.py               # 标准化统一入口：download / convert / validate / sync
├── configs/
│   └── binance_1min_6symbols.yaml     # 正式 6-symbol 配置
├── manifests/
│   └── official_1min_6symbols/        # 标准化产物清单
├── qlib_data_1min/                    # 已生成的Qlib数据（当前仓库中的样例产物）
│   ├── calendars/
│   └── instruments/
└── data_get_try.ipynb                 # 试验Notebook
```

## 环境依赖

确保已按 `a6_customizations/environment.yml` 创建环境并安装项目。

核心依赖：
- `requests`
- `tqdm`
- `pandas`
- `pyarrow`（用于 Parquet）
- `loguru`

## 标准化入口

正式任务默认使用配置文件：

`a6_customizations/binance_data-qlib/configs/binance_1min_6symbols.yaml`

正式命令统一走：

```bash
python a6_customizations/binance_data-qlib/run_data_pipeline.py <command> \
  --config a6_customizations/binance_data-qlib/configs/binance_1min_6symbols.yaml
```

支持四个命令：

- `download`：批量下载并更新原始 zip，同时写 `raw_zip_manifest.json`
- `convert`：把 zip 转成 Parquet 和 Qlib，同时更新 `parquet_manifest.json`、`qlib_manifest.json`
- `validate`：执行 6-symbol contract 检查，并写 `contract_summary.json`
- `sync`：顺序执行 `download -> convert -> validate`

推荐日常操作：

```bash
python a6_customizations/binance_data-qlib/run_data_pipeline.py sync \
  --config a6_customizations/binance_data-qlib/configs/binance_1min_6symbols.yaml
```

## 使用流程

### 1. 批量下载 Binance 1m 数据

脚本：`binance_batch_downloader.py`

默认会按以下 URL 模式下载：

```text
https://data.binance.vision/data/futures/um/daily/klines/{pair}/1m/{pair}-1m-{date}.zip
```

标准化命令：

```bash
python a6_customizations/binance_data-qlib/run_data_pipeline.py download \
  --config a6_customizations/binance_data-qlib/configs/binance_1min_6symbols.yaml
```

底层脚本仍可单独使用，关键参数包括：
- `pairs`: 交易对列表，如 `['BTCUSDT', 'ETHUSDT']`
- `download_path`: 本地下载目录
- `start_date`: 起始日期（`YYYY-MM-DD`）
- `end_date`: 结束日期（`YYYY-MM-DD`），为空时默认按当前日期推导
- `overwrite_mode`: `True` 全量覆盖，`False` 仅补齐缺失日期
- `enable_logging`: 是否输出详细日志

### 2. 转换为 Qlib 数据格式

脚本：`convert_binance_zip_to_qlib.py`

标准化命令：

```bash
python a6_customizations/binance_data-qlib/run_data_pipeline.py convert \
  --config a6_customizations/binance_data-qlib/configs/binance_1min_6symbols.yaml
```

底层正式重建（固定 6-symbol，写入正式目录）：

```bash
python a6_customizations/binance_data-qlib/convert_binance_zip_to_qlib.py \
  --source_dir a6_customizations/binance_data-qlib/binance_data_1min \
  --csv_dir a6_customizations/binance_data-qlib/csv_data_1min \
  --qlib_dir a6_customizations/binance_data-qlib/qlib_data_1min \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT \
  --freq 1min
```

局部实验（例如只验证 `BTCUSDT`、`ETHUSDT`，必须写入独立目录）：

```bash
python a6_customizations/binance_data-qlib/convert_binance_zip_to_qlib.py \
  --source_dir a6_customizations/binance_data-qlib/binance_data_1min \
  --csv_dir a6_customizations/binance_data-qlib/csv_data_1min_pair_experiment \
  --qlib_dir a6_customizations/binance_data-qlib/qlib_data_1min_pair_experiment \
  --symbols BTCUSDT,ETHUSDT \
  --freq 1min
```

说明：

- 正式 `qlib_data_1min` 只接受完整 6-symbol 重建。
- 如果传入的 `symbols` 少于 6 个，脚本会拒绝写入正式 `csv_data_1min` / `qlib_data_1min`，避免静默把 universe 从 6 个缩成 2 个。
- 局部实验仍然允许，但必须使用独立输出目录。

参数说明：
- `source_dir`: zip 原始数据目录（支持按 `symbol` 子目录组织）
- `csv_dir`: 中间 Parquet 输出目录
- `qlib_dir`: 最终 Qlib 数据目录
- `symbols`: 逗号分隔交易对列表
- `freq`: 频率，当前使用 `1min`

## 字段说明（Qlib侧）

转换后主要字段：
- `open`
- `high`
- `low`
- `close`
- `volume`
- `vwap`
- `count`
- `quote_volume`
- `taker_buy_volume`
- `taker_buy_quote_volume`
- `factor`（固定为 `1.0`，在数字货币场景可忽略）

说明：
- Binance 原始列中常见 `taker_buy_base_volume`，在本模块中统一落为 `taker_buy_volume`。
- `vwap` 由 `quote_volume / volume` 计算得到；当 `volume <= 0` 或缺失时，回退使用 `close`。
- 时间统一解析并格式化为 `YYYY-MM-DD HH:MM:SS`。

如果本地已经有正式 6-symbol `Parquet`，可以直接复用并补算 `vwap`，再重建正式 Qlib 数据：

```bash
python a6_customizations/binance_data-qlib/convert_binance_zip_to_qlib.py \
  --csv_dir a6_customizations/binance_data-qlib/csv_data_1min \
  --qlib_dir a6_customizations/binance_data-qlib/qlib_data_1min \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT \
  --freq 1min \
  --reuse_existing_parquet
```

## 产物位置

- 原始 zip：`a6_customizations/binance_data-qlib/binance_data_1min/`
- 中间 Parquet：`a6_customizations/binance_data-qlib/csv_data_1min/`
- Qlib 数据：`a6_customizations/binance_data-qlib/qlib_data_1min/`
- 标准化 manifest：`a6_customizations/binance_data-qlib/manifests/official_1min_6symbols/`

manifest 说明：

- `raw_zip_manifest.json`：zip 下载范围、数量、失败记录与本地清单
- `parquet_manifest.json`：每个 symbol 的 Parquet 起止时间、行数
- `qlib_manifest.json`：Qlib instruments、feature 字段、calendar 概览
- `contract_summary.json`：完整 6-symbol contract 检查结果

## 仓库提交约定

- `binance_data_1min/` 原始 zip 默认只保留本地，不提交到 Git
- `csv_data_1min*/` 中间 `Parquet` 默认只保留本地，不提交到 Git
- `qlib_data_1min/features/` 视为可重建的 Qlib 二进制特征，不提交到 Git
- `manifests/official_1min_6symbols/*.json` 作为轻量契约与复现摘要，继续纳入 Git
- `data_get_try.ipynb` 允许提交，但仓库中的提交版本会自动清空 `output` 与 `execution_count`

## 注意事项

- 下载失败会被记录，可通过 `get_failed_downloads()` 查看。
- 单个文件下载会先写入 `.part` 临时文件，只有 ZIP 结构校验、内部 CSV/CRC 校验、Binance `.CHECKSUM` 的 SHA256 校验全部通过后，才会落为正式 `.zip`。
- 更新模式会先扫描本地已有 `.zip`，发现下载残片、HTML错误页或损坏ZIP时会清理坏文件，并把对应日期重新放回下载队列，避免坏数据被“已存在文件”逻辑跳过。
- 单个文件下载失败或校验失败时会清理无效文件，避免脏数据残留。
- 之前仓库里出现过“原始 zip 是 6-symbol，但 Qlib 只剩 2-symbol”的情况，原因是有人用局部 `--symbols BTCUSDT,ETHUSDT` 重写了正式 `qlib_data_1min`。当前脚本已禁止这种静默缩 universe 的写法。
- Notebook `data_get_try.ipynb` 保留作探索用途，不再视为正式入口。正式流程以 `config + CLI + manifest` 为准。
- 如果后续要接入更高频或更多类型数据（如 trades、bookTicker），建议在 `a6_customizations` 下新增并独立维护新模块与 README。
