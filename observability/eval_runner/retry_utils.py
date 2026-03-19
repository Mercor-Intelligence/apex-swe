"""
Retry utilities with exponential backoff.

Provides a single, consolidated implementation of retry logic
for use across the evaluation system.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Tuple, Type, TypeVar, Optional

from eval_runner.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')

# Exceptions that are typically transient and worth retrying
TRANSIENT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,  # Includes network errors
)


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> T:
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Function to call (no arguments)
        max_retries: Maximum number of retries (0 = no retries, just one attempt)
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        retryable_exceptions: Tuple of exception types that should trigger a retry
        on_retry: Optional callback(exception, attempt_number) called before each retry
        
    Returns:
        Result from func on success
        
    Raises:
        Last exception if all retries exhausted
    """
    last_exception: Optional[Exception] = None
    
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            
            if attempt >= max_retries:
                # Clear traceback reference to prevent memory accumulation
                # before re-raising
                raise e from None
            
            # Calculate delay with jitter
            delay = min(base_delay * (exponential_base ** attempt), max_delay)
            delay = delay * (0.5 + random.random())  # Add jitter
            
            if on_retry:
                on_retry(e, attempt + 1)
            else:
                logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {e}")
            
            time.sleep(delay)
    
    # This should not be reached, but just in case
    if last_exception is not None:
        raise last_exception from None
    raise RuntimeError("Unexpected state in retry_with_backoff")
