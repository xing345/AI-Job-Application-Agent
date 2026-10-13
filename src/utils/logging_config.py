"""统一日志配置。

日志格式：时间 | 级别 | run_id | 节点 | 岗位 | 事件 | 结果/错误 | 耗时
不记录 API Key、Cookie、密码、完整简历和不必要的个人信息。
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


class AgentLogFormatter(logging.Formatter):
    """Agent 专用日志格式化器。

    支持通过 extra 参数传入 run_id、node、job、event、elapsed 等字段。
    """

    def format(self, record: logging.LogRecord) -> str:
        run_id = getattr(record, "run_id", "-")
        node = getattr(record, "node", "-")
        job = getattr(record, "job", "-")
        event = getattr(record, "event", "-")
        elapsed = getattr(record, "elapsed", "")

        # 截断过长的 job 标识
        if isinstance(job, str) and len(job) > 40:
            job = job[:37] + "..."

        prefix = f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} | {record.levelname:<7} | run={run_id:<8} | node={node:<16} | job={job:<20} | event={event:<20}"
        if elapsed:
            prefix += f" | {elapsed}"

        msg = record.getMessage()
        return f"{prefix} | {msg}"


def setup_logging(
    verbose: bool = False,
    run_id: str = "",
    log_file: Optional[str] = None,
) -> logging.Logger:
    """配置全局日志。

    Args:
        verbose: 是否启用 DEBUG 级别
        run_id: 本次运行的 ID，用于日志关联
        log_file: 自定义日志文件路径，默认按时间戳生成

    Returns:
        配置后的 root logger
    """
    level = logging.DEBUG if verbose else logging.INFO

    _LOG_DIR.mkdir(exist_ok=True)
    if log_file is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = str(_LOG_DIR / f"agent_{timestamp}.log")

    formatter = AgentLogFormatter()

    # 文件处理器
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有处理器，避免重复
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 降低第三方库日志级别
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging initialized: level=%s file=%s run_id=%s", level, log_file, run_id)

    return root_logger


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    run_id: str = "",
    node: str = "",
    job: str = "",
    event: str = "",
    elapsed: str = "",
) -> None:
    """带上下文信息的日志记录辅助函数。

    用法：
        log_with_context(logger, logging.INFO, "匹配完成",
                         run_id=state.run_id, node="match_jobs",
                         job=job_title, event="match_complete", elapsed="1.2s")
    """
    extra = {}
    if run_id:
        extra["run_id"] = run_id
    if node:
        extra["node"] = node
    if job:
        extra["job"] = job
    if event:
        extra["event"] = event
    if elapsed:
        extra["elapsed"] = elapsed

    logger.log(level, message, extra=extra if extra else None)
