from pathlib import Path
from typing import Union, Optional, List, Dict, Any
from loguru import logger
from datetime import datetime, timedelta

from binance_data_downloader import BinanceDataDownloader

"""
从币安公开数据库批量下载数据的函数
针对"https://data.binance.vision/data/futures/um/daily/klines/{pair}/1m/{pair}-1m-{date}.zip"的格式批量生成链接并且调用 BinanceDataDownloader
下载器默认下载时间为最后一天
"""

class BinanceBatchDownloader:
    """币安批量数据下载管理器"""
    
    def __init__(
        self,
        pairs: List[str],
        download_path: Union[str, Path],
        start_date: str,
        end_date: Optional[str] = None,
        overwrite_mode: bool = False,
        enable_logging: bool = True,
    ):
        """
        Args:
            pairs: 交易对列表，如 ['BTCUSDT', 'ETHUSDT']
            download_path: 下载路径
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'；若为空则默认到今天
            overwrite_mode: True=覆盖模式，False=更新模式
            enable_logging: True=显示详细日志，False=静默模式（只显示关键信息）
        """
        self.pairs = self._normalize_pairs(pairs)
        self.download_path = Path(download_path)
        self.start_date = start_date
        self.end_date = end_date
        self.overwrite_mode = overwrite_mode
        self.enable_logging = enable_logging
        self.downloader = BinanceDataDownloader()
        
        # 初始化失败记录字典
        self.failed_downloads: Dict[str, List[str]] = {pair: [] for pair in self.pairs}
        
        # 配置日志输出
        self._configure_logging()

    @staticmethod
    def _normalize_pairs(pairs: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for pair in pairs:
            pair_text = str(pair).strip().upper()
            if not pair_text or pair_text in seen:
                continue
            normalized.append(pair_text)
            seen.add(pair_text)
        if not normalized:
            raise ValueError("pairs 不能为空")
        return normalized
        
    def _configure_logging(self) -> None:
        """配置日志输出级别"""
        logger.remove()  # 移除现有的处理器
        
        if self.enable_logging:
            # 详细日志模式
            logger.add(
                sink=lambda message: print(message, end=''),
                format="{time:YYYY-MM-DD HH:mm:ss,SSS} - {level} - {message}\n",
                level="INFO"
            )
        else:
            # 静默模式，只显示WARNING及以上级别
            logger.add(
                sink=lambda message: print(message, end=''),
                format="{message}\n",
                level="WARNING"
            )
    
    def _print_status(self, message: str) -> None:
        """无论是否开启日志都显示的状态信息"""
        print(f"[STATUS] {message}")
    
    def _generate_date_range(self) -> List[str]:
        """生成从开始日期到结束日期的日期列表"""
        start = datetime.strptime(self.start_date, '%Y-%m-%d')
        end_date = self.end_date or datetime.now().strftime('%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        if end < start:
            raise ValueError(f"end_date({end_date}) 早于 start_date({self.start_date})")
        
        date_list = []
        current = start
        while current <= end:
            date_list.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
            
        return date_list
    
    def _get_existing_dates(self, pair_path: Path) -> List[str]:
        """获取已存在且通过ZIP结构校验的数据日期；坏ZIP会被清理并重新下载。"""
        if not pair_path.exists():
            return []

        existing_dates = []
        invalid_files = []
        for file_path in sorted(pair_path.iterdir()):
            if file_path.suffix != '.zip':
                continue
            if self.downloader.validate_existing_zip(file_path, cleanup_invalid=True):
                existing_dates.append(file_path.stem[-10:])
            else:
                invalid_files.append(file_path.name)

        if invalid_files:
            self._print_status(f"发现并清理 {len(invalid_files)} 个坏ZIP，将重新下载: {invalid_files}")
        return existing_dates
    
    def _generate_download_url(self, pair: str, date: str) -> str:
        """生成下载URL"""
        return f"https://data.binance.vision/data/futures/um/daily/klines/{pair}/1m/{pair}-1m-{date}.zip"
    
    def get_failed_downloads(self) -> Dict[str, List[str]]:
        """获取下载失败的记录
        
        Returns:
            Dict[str, List[str]]: {交易对: [失败日期列表]}
        """
        return {pair: dates for pair, dates in self.failed_downloads.items() if dates}
    
    def download_all(self) -> Dict[str, Any]:
        """执行批量下载"""
        dates = self._generate_date_range()
        date_range_end = self.end_date or dates[-1]
        self._print_status(f"开始批量下载，交易对: {self.pairs}, 日期范围: {self.start_date} 到 {date_range_end}")
        self._print_status(f"模式: {'覆盖模式' if self.overwrite_mode else '更新模式'}")
        
        total_success = 0
        total_failed = 0
        pair_summaries: Dict[str, Any] = {}
        
        for pair in self.pairs:
            self._print_status(f"正在处理交易对: {pair}")
            pair_path = self.download_path / pair
            BinanceDataDownloader.ensure_directory(pair_path)
            existing_dates: List[str] = []
            
            if self.overwrite_mode:
                download_dates = dates
                self._print_status(f"覆盖模式：将下载 {len(download_dates)} 个文件")
            else:
                existing_dates = self._get_existing_dates(pair_path)
                download_dates = [date for date in dates if date not in existing_dates]
                self._print_status(f"更新模式：跳过 {len(existing_dates)} 个已存在文件，将下载 {len(download_dates)} 个新文件")
            
            success_count = 0
            failed_count = 0
            
            for date in download_dates:
                url = self._generate_download_url(pair, date)
                result = self.downloader.download(url, pair_path)
                if result:
                    success_count += 1
                    total_success += 1
                else:
                    failed_count += 1
                    total_failed += 1
                    self.failed_downloads[pair].append(date)
                    
            self._print_status(f"{pair} 完成：成功 {success_count}，失败 {failed_count}")
            pair_summaries[pair] = {
                "existing_dates": len(existing_dates) if not self.overwrite_mode else 0,
                "requested_dates": len(download_dates),
                "success_count": success_count,
                "failed_count": failed_count,
                "failed_dates": list(self.failed_downloads.get(pair, [])),
            }
            
        self._print_status(f"批量下载完成！总计：成功 {total_success}，失败 {total_failed}")
        
        # 显示失败统计
        failed_summary = self.get_failed_downloads()
        if failed_summary:
            self._print_status("下载失败统计：")
            for pair, failed_dates in failed_summary.items():
                self._print_status(f"  {pair}: {len(failed_dates)} 个文件失败")
                if self.enable_logging:  # 只在详细模式下显示具体日期
                    self._print_status(f"    失败日期: {failed_dates}")
        return {
            "pairs": self.pairs,
            "start_date": self.start_date,
            "end_date": date_range_end,
            "overwrite_mode": self.overwrite_mode,
            "total_success": total_success,
            "total_failed": total_failed,
            "failed_downloads": failed_summary,
            "pair_summaries": pair_summaries,
        }


# 使用示例
if __name__ == "__main__":
    # 静默模式示例
    batch_downloader = BinanceBatchDownloader(
        pairs=['BTCUSDT', 'ETHUSDT'],
        download_path="binance_data_1min",
        start_date='2025-01-01',
        end_date='2025-01-31',
        overwrite_mode=False,
        enable_logging=False  # 静默模式
    )
    
    # 执行下载
    batch_downloader.download_all()
    
    # 获取失败记录
    failed_records = batch_downloader.get_failed_downloads()
    print("详细失败记录:", failed_records)
    
    # 详细日志模式示例
    verbose_downloader = BinanceBatchDownloader(
        pairs=['ADAUSDT'],
        download_path="binance_data_1min",
        start_date='2025-06-01',
        end_date='2025-06-03',
        overwrite_mode=True,
        enable_logging=True  # 详细日志
    )
    
    verbose_downloader.download_all()
