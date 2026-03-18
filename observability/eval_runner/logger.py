"""
Centralized logging configuration for the evaluation runner.

Provides structured logging with consistent formatting across all modules.
"""

import logging
import sys


# Module-level logger instances
_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str = "eval_runner") -> logging.Logger:
    """Get a logger instance with consistent configuration.
    
    Args:
        name: Logger name (typically module name)
        
    Returns:
        Configured logger instance
    """
    if name in _loggers:
        return _loggers[name]
    
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        
        # Console handler with INFO level by default
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # Format with timestamp, level, and task context
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # Prevent propagation to root logger
        logger.propagate = False
    
    _loggers[name] = logger
    return logger


def set_log_level(level: int | str) -> None:
    """Set the log level for all eval_runner loggers.
    
    Args:
        level: Logging level (e.g., logging.DEBUG, "DEBUG")
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    
    for logger in _loggers.values():
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)


class TaskLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that automatically prefixes messages with task_id."""
    
    def __init__(self, logger: logging.Logger, task_id: str):
        super().__init__(logger, {"task_id": task_id})
        self.task_id = task_id
    
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        return f"[{self.task_id}] {msg}", kwargs


def get_task_logger(task_id: str, name: str = "eval_runner") -> TaskLoggerAdapter:
    """Get a logger that automatically prefixes messages with task_id.
    
    Args:
        task_id: Task identifier to include in log messages
        name: Base logger name
        
    Returns:
        Logger adapter with task context
    """
    base_logger = get_logger(name)
    return TaskLoggerAdapter(base_logger, task_id)


# Create default logger
logger = get_logger()
