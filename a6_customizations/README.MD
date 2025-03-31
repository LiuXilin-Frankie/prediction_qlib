# 基于Qlib的预测库

预测的目标是：
1. BTCUSDT 10min后的收益，基于1min的kline
2. A股市场 10min后的收益，基于1min的kline
3. 商品期权期货市场 波动率和高频价格变动率，基于LOB和trade数据

## 项目结构

项目被重构为模块化设计，分为以下几个主要组件：

```
└── prediction_qlib/        # 开源项目 qlib 的源码以及个人添加的一些代码
    ├── a6_customizations   # lxl自定义的一些文件，主要包含环境配置，说明文件等等
    └── others              # 其它qlib下的文件

```


### 使用Conda设置环境

```bash
cd a6_customizations/
conda env remove -n prediction_qlib -y
conda env update --file environment.yml --prune
conda activate prediction_qlib
cd ..
python setup.py install
```

### 下载数据
```shell
cd qlib
python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn
cd ..
```

### 运行模型进行测试
请不要直接在qlib路径下进行测试
```
cd examples  # 避免在包含 `qlib` 的目录下运行程序
qrun benchmarks/LightGBM/workflow_config_lightgbm.yaml
```

## 运行说明







