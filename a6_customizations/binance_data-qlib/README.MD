# Binance 1分钟数据获取与Qlib转换

本模块用于从 Binance 公共数据源批量下载永续合约 K 线数据（1m），并转换为 Qlib 可直接使用的数据格式。

## 模块目标

- 从 `https://data.binance.vision` 下载按天打包的 1m K 线 zip 文件。
- 对每个下载文件做 SHA256 校验（使用 Binance 提供的 `.CHECKSUM`）。
- 将 zip 中原始数据整理为中间 Parquet。
- 将 Parquet 转储为 Qlib 二进制格式（`features/`、`calendars/`、`instruments/`）。

## 目录结构

```text
binance_data-qlib/
├── binance_data_downloader.py         # 单文件下载+校验
├── binance_batch_downloader.py        # 按交易对/日期批量下载
├── convert_binance_zip_to_qlib.py     # zip -> parquet -> qlib
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

## 使用流程

### 1. 批量下载 Binance 1m 数据

脚本：`binance_batch_downloader.py`

默认会按以下 URL 模式下载：

```text
https://data.binance.vision/data/futures/um/daily/klines/{pair}/1m/{pair}-1m-{date}.zip
```

示例（可直接在脚本内修改参数后运行）：

```bash
python a6_customizations/binance_data-qlib/binance_batch_downloader.py
```

关键参数（在 `BinanceBatchDownloader(...)` 中配置）：
- `pairs`: 交易对列表，如 `['BTCUSDT', 'ETHUSDT']`
- `download_path`: 本地下载目录
- `start_date`: 起始日期（`YYYY-MM-DD`）
- `overwrite_mode`: `True` 全量覆盖，`False` 仅补齐缺失日期
- `enable_logging`: 是否输出详细日志

### 2. 转换为 Qlib 数据格式

脚本：`convert_binance_zip_to_qlib.py`

示例命令：

```bash
python a6_customizations/binance_data-qlib/convert_binance_zip_to_qlib.py \
  --source_dir a6_customizations/binance_data-qlib/binance_data_1min \
  --csv_dir a6_customizations/binance_data-qlib/csv_data_1min \
  --qlib_dir a6_customizations/binance_data-qlib/qlib_data_1min \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT \
  --freq 1min
```

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

如果本地已经有中间 `Parquet`，可以直接复用并补算 `vwap`，再重建 Qlib 数据：

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

## 注意事项

- 下载失败会被记录，可通过 `get_failed_downloads()` 查看。
- 单个文件下载失败或校验失败时会清理无效文件，避免脏数据残留。
- 如果后续要接入更高频或更多类型数据（如 trades、bookTicker），建议在 `a6_customizations` 下新增并独立维护新模块与 README。
