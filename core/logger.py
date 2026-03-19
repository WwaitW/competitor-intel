"""
logger.py — 统一日志配置（P2-⑰）

同时输出到：
  - 控制台（INFO 及以上）
  - logs/competitor_intel.log（DEBUG 及以上，含后台任务详情）

用法：
    from core.logger import get_logger
    logger = get_logger(__name__)
    logger.info("任务完成")
    logger.warning("Key 未配置")
    logger.error("分析失败: %s", exc)
"""
import logging
import os


def get_logger(name: str) -> logging.Logger:
    """
    获取命名 logger。首次调用时自动注册控制台 + 文件 handler，
    重复调用同名 logger 直接返回已有实例（无重复 handler）。
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台：INFO+
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 文件：DEBUG+，写入 logs/competitor_intel.log
    try:
        _log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
        os.makedirs(_log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(_log_dir, "competitor_intel.log"),
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass  # 文件 handler 失败时静默降级为仅控制台输出

    return logger
