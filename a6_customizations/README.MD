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

- `binance_data-qlib`：Binance 1分钟数据下载、校验、转换为Qlib数据格式  
  详细文档见：[a6_customizations/binance_data-qlib/README.MD](./binance_data-qlib/README.MD)

- `qlib_btc_5min_baseline`：使用Qlib内置 `Alpha158` 因子与 `LightGBM`，对 `BTCUSDT` 的 `5分钟` 事件合约进行滚动训练、阈值筛选与测试集交易模拟的 baseline 方案  
  详细文档见：[a6_customizations/qlib_btc_5min_baseline/README.MD](./qlib_btc_5min_baseline/README.MD)


