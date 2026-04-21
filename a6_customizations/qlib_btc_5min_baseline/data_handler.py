from qlib.contrib.data.handler import Alpha158
from qlib.contrib.data.loader import Alpha158DL


DEFAULT_INFER_PROCESSORS = []

DEFAULT_LEARN_PROCESSORS = [
    {"class": "DropnaLabel"},
]


class BTC5MinAlpha158(Alpha158):
    """Alpha158 variant for BTCUSDT 5-minute event contracts.

    This handler keeps the built-in Alpha158 factor family, including VWAP
    features derived from Binance `quote_volume / volume`, and uses a forward
    return label aligned with:

    - decision time: t
    - entry price: open at t + 1 minute
    - settlement price: open at t + 6 minutes
    """

    def __init__(
        self,
        rolling_windows=(5, 10, 20, 30, 60),
        price_windows=(0,),
        volume_windows=(0,),
        include_ops=None,
        exclude_ops=("RANK",),
        entry_offset_minutes=1,
        horizon_minutes=5,
        infer_processors=None,
        learn_processors=None,
        **kwargs,
    ):
        self.rolling_windows = tuple(rolling_windows)
        self.price_windows = tuple(price_windows)
        self.volume_windows = tuple(volume_windows)
        self.include_ops = include_ops
        self.exclude_ops = tuple(exclude_ops)
        self.entry_offset_minutes = int(entry_offset_minutes)
        self.horizon_minutes = int(horizon_minutes)

        super().__init__(
            infer_processors=DEFAULT_INFER_PROCESSORS if infer_processors is None else infer_processors,
            learn_processors=DEFAULT_LEARN_PROCESSORS if learn_processors is None else learn_processors,
            **kwargs,
        )

    def get_feature_config(self):
        conf = {
            "kbar": {},
            "price": {
                "windows": list(self.price_windows),
                "feature": ["OPEN", "HIGH", "LOW", "CLOSE", "VWAP"],
            },
            "volume": {
                "windows": list(self.volume_windows),
            },
            "rolling": {
                "windows": list(self.rolling_windows),
                "include": self.include_ops,
                "exclude": list(self.exclude_ops),
            },
        }
        return Alpha158DL.get_feature_config(conf)

    def get_label_config(self):
        exit_offset = self.entry_offset_minutes + self.horizon_minutes
        expr = f"Ref($open, -{exit_offset})/Ref($open, -{self.entry_offset_minutes}) - 1"
        return [expr], ["LABEL0"]
