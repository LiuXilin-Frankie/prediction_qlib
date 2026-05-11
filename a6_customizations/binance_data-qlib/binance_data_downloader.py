import requests
import hashlib
import zipfile
from pathlib import Path
from tqdm import tqdm
from urllib.parse import urlparse
from typing import Union, Optional
from loguru import logger

"""
该类是binance数据的下载器给定一个数据url和文件下载的路径
程序会下载数据到指定路径并且校验文件的完整性
校验文件由binance数据库提供

示例：

downloader = BinanceDataDownloader()
download_url = "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2025-04-06.zip"
local_target_directory = "binance_data_downloads"

downloaded_file_path = downloader.download(download_url, local_target_directory)
"""


# 配置loguru日志格式，保持与原logging相同的输出格式
logger.remove()  # 移除默认handler
logger.add(
    sink=lambda message: print(message, end=''),
    format="{time:YYYY-MM-DD HH:mm:ss,SSS} - {level} - {message}\n",
    level="INFO"
)

class BinanceDataDownloader:
    """
    Binance数据下载器类，用于下载ZIP文件及其CHECKSUM文件并验证完整性。
    """
    
    def __init__(self, chunk_size: int = 8192, timeout: int = 60, max_retries: int = 3):
        """
        初始化下载器配置。
        
        Args:
            chunk_size (int): 下载文件时每次读取的字节数
            timeout (int): HTTP请求的超时时间
            max_retries (int): 单个文件下载和校验失败后的最大尝试次数
        """
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
    
    def _parse_url(self, url: str) -> str:
        """
        从URL中解析出文件名。
        
        Args:
            url (str): 文件下载URL
            
        Returns:
            str: 从URL路径中提取的文件名
        """
        parsed_url = urlparse(url)
        file_name = Path(parsed_url.path).name
        return file_name
    
    @staticmethod
    def ensure_directory(target_directory: Path) -> bool:
        """
        确保目标目录存在，如果不存在则创建。
        
        Args:
            target_directory (Path): 目标目录路径
            
        Returns:
            bool: 目录创建是否成功
        """
        try:
            target_directory.mkdir(parents=True, exist_ok=True)
            logger.info(f"确保目标目录存在: {target_directory}")
            return True
        except OSError as e:
            logger.error(f"无法创建目标目录 {target_directory}: {e}")
            return False
    
    def _download_zip_file(self, url: str, file_path: Path) -> bool:
        """
        下载ZIP文件，带进度条显示。先写入.part临时文件，完成后再原子替换目标文件。
        
        Args:
            url (str): 文件下载URL
            file_path (Path): 本地文件保存路径
            
        Returns:
            bool: 下载是否成功
        """
        file_name = file_path.name
        logger.info(f"开始下载文件: {file_name} from {url}")
        part_path = file_path.with_name(file_path.name + ".part")
        
        try:
            with requests.get(url, stream=True, timeout=self.timeout) as r:
                r.raise_for_status()
                
                total_size = int(r.headers.get('content-length', 0))
                
                with tqdm(total=total_size, unit='B', unit_scale=True, desc=file_name) as pbar:
                    with open(part_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=self.chunk_size):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))

            if total_size and part_path.stat().st_size != total_size:
                logger.error(
                    f"文件 {file_name} 下载字节数不匹配: "
                    f"expected={total_size}, actual={part_path.stat().st_size}"
                )
                return False

            part_path.replace(file_path)
            logger.info(f"文件下载完成: {file_path}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"下载文件 {file_name} 失败: {e}")
            return False
        except IOError as e:
            logger.error(f"写入文件 {file_path} 失败: {e}")
            return False
        finally:
            if part_path.exists():
                self._cleanup_files(part_path)
    
    def _download_checksum_file(self, checksum_url: str, checksum_path: Path) -> Optional[str]:
        """
        下载CHECKSUM文件并解析出期望的校验和。
        
        Args:
            checksum_url (str): CHECKSUM文件下载URL
            checksum_path (Path): CHECKSUM文件本地保存路径
            
        Returns:
            Optional[str]: 期望的校验和字符串，失败时返回None
        """
        checksum_file_name = checksum_path.name
        logger.info(f"开始下载校验和文件: {checksum_file_name} from {checksum_url}")
        
        try:
            with requests.get(checksum_url, timeout=self.timeout) as r:
                r.raise_for_status()
                expected_checksum_line = r.text.strip()
                # CHECKSUM文件内容通常是 "hash值 文件名"
                expected_checksum = expected_checksum_line.split()[0] if expected_checksum_line else ""
                if len(expected_checksum) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_checksum):
                    logger.error(f"校验和文件格式异常: {expected_checksum_line}")
                    return None
                
                with open(checksum_path, 'w') as f:
                    f.write(expected_checksum_line)
                    
            logger.info(f"校验和文件下载完成: {checksum_path}")
            return expected_checksum
            
        except requests.exceptions.RequestException as e:
            logger.error(f"下载校验和文件 {checksum_file_name} 失败: {e}")
            return None
        except IOError as e:
            logger.error(f"写入校验和文件 {checksum_path} 失败: {e}")
            return None
    
    def _verify_file_integrity(self, file_path: Path, expected_checksum: str) -> bool:
        """
        验证文件的SHA256校验和。
        
        Args:
            file_path (Path): 要验证的文件路径
            expected_checksum (str): 期望的校验和
            
        Returns:
            bool: 验证是否通过
        """
        file_name = file_path.name
        logger.info(f"开始验证文件 {file_name} 的完整性...")
        
        try:
            # 计算下载文件的SHA256
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(self.chunk_size), b''):
                    hasher.update(chunk)
            calculated_checksum = hasher.hexdigest()
            
            if calculated_checksum == expected_checksum:
                logger.info(f"文件 {file_name} 校验成功！")
                return True
            else:
                logger.error(f"文件 {file_name} 校验失败！")
                logger.error(f"预期校验和: {expected_checksum}")
                logger.error(f"计算校验和: {calculated_checksum}")
                return False
                
        except FileNotFoundError:
            logger.error(f"文件 {file_path} 未找到，无法进行校验。")
            return False
        except Exception as e:
            logger.error(f"校验文件 {file_name} 时发生未知错误: {e}")
            return False

    def _verify_zip_structure(self, file_path: Path) -> bool:
        """
        验证下载结果确实是可读取的ZIP文件，且内部包含CSV数据文件。

        这一步用于防止HTTP错误页、下载残片、空ZIP等文件仅靠扩展名混入数据目录。
        """
        file_name = file_path.name
        logger.info(f"开始验证ZIP结构: {file_name}")

        if not file_path.exists():
            logger.error(f"ZIP文件不存在: {file_path}")
            return False
        if file_path.stat().st_size <= 0:
            logger.error(f"ZIP文件为空: {file_path}")
            return False
        if not zipfile.is_zipfile(file_path):
            logger.error(f"文件不是有效ZIP: {file_path}")
            return False

        try:
            with zipfile.ZipFile(file_path) as zf:
                members = [name for name in zf.namelist() if not name.endswith("/")]
                csv_members = [name for name in members if name.lower().endswith(".csv")]
                if not members:
                    logger.error(f"ZIP内没有数据文件: {file_path}")
                    return False
                if not csv_members:
                    logger.error(f"ZIP内没有CSV数据文件: {file_path}, members={members[:5]}")
                    return False
                bad_member = zf.testzip()
                if bad_member is not None:
                    logger.error(f"ZIP内部文件CRC校验失败: {file_path}, bad_member={bad_member}")
                    return False
        except zipfile.BadZipFile as e:
            logger.error(f"ZIP文件损坏: {file_path}, error={e}")
            return False
        except Exception as e:
            logger.error(f"验证ZIP结构时发生未知错误: {file_path}, error={e}")
            return False

        logger.info(f"ZIP结构验证成功: {file_name}")
        return True

    def validate_existing_zip(self, file_path: Union[Path, str], cleanup_invalid: bool = False) -> bool:
        """
        验证本地已存在的ZIP文件是否可用于后续转换。

        Args:
            file_path: 本地ZIP文件路径
            cleanup_invalid: 若验证失败，是否删除该坏文件
        """
        file_path = Path(file_path)
        is_valid = self._verify_zip_structure(file_path)
        if not is_valid and cleanup_invalid:
            self._cleanup_files(file_path, file_path.with_name(file_path.name + ".part"))
        return is_valid
    
    def _cleanup_files(self, *file_paths: Path) -> None:
        """
        清理指定的文件。
        
        Args:
            *file_paths: 要清理的文件路径列表
        """
        for file_path in file_paths:
            if file_path.exists():
                try:
                    file_path.unlink()
                    logger.info(f"已清理文件: {file_path}")
                except Exception as e:
                    logger.error(f"清理文件 {file_path} 失败: {e}")
    
    def download(
        self,
        url: str,
        target_directory: Union[Path, str]
    ) -> Optional[Path]:
        """
        从Binance数据源下载ZIP文件及其CHECKSUM文件，并验证下载的完整性。
        
        Args:
            url (str): 要下载的ZIP文件的URL
            target_directory (Union[Path, str]): 文件下载到本地的目标目录
            
        Returns:
            Optional[Path]: 如果下载和验证成功，返回下载文件的本地路径；否则返回None
        """
        target_directory = Path(target_directory)
        
        # 1. 解析URL，获取文件名
        file_name = self._parse_url(url)
        zip_file_path = target_directory / file_name
        checksum_file_name = file_name + '.CHECKSUM'
        checksum_file_path = target_directory / checksum_file_name
        checksum_url = url + '.CHECKSUM'
        
        # 2. 创建目标目录
        if not self.ensure_directory(target_directory):
            return None
        
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"下载尝试 {attempt}/{self.max_retries}: {file_name}")

            # 3. 下载ZIP文件
            if not self._download_zip_file(url, zip_file_path):
                self._cleanup_files(checksum_file_path)
                continue

            # 4. 先验证ZIP结构，快速排除HTML错误页、下载残片和空ZIP
            if not self._verify_zip_structure(zip_file_path):
                self._cleanup_files(zip_file_path, checksum_file_path)
                continue

            # 5. 下载CHECKSUM文件
            expected_checksum = self._download_checksum_file(checksum_url, checksum_file_path)
            if expected_checksum is None:
                self._cleanup_files(zip_file_path, checksum_file_path)
                continue

            # 6. 验证文件完整性
            if not self._verify_file_integrity(zip_file_path, expected_checksum):
                self._cleanup_files(zip_file_path, checksum_file_path)
                continue

            self._cleanup_files(checksum_file_path)
            return zip_file_path

        logger.error(f"文件 {file_name} 下载失败，已达到最大尝试次数: {self.max_retries}")
        return None


# --- 使用示例 ---
if __name__ == "__main__":
    # 使用类的方式
    downloader = BinanceDataDownloader()
    download_url = "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2025-04-06.zip"
    local_target_directory = "binance_data_1min/BTCUSDT/"
    
    downloaded_file_path = downloader.download(download_url, local_target_directory)
