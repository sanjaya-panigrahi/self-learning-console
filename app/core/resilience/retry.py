"""
Exponential backoff retry logic for transient failures.
"""
import time
import logging
import random
from typing import Callable, TypeVar, Any
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar("T")


def exponential_backoff_retry(
    max_retries: int = 3,
    initial_delay_ms: int = 100,
    max_delay_ms: int = 5000,
    jitter: bool = True,
    exception_types: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay_ms: Initial delay in milliseconds (100ms)
        max_delay_ms: Maximum delay cap in milliseconds (5s)
        jitter: Add randomness to prevent thundering herd
        exception_types: Exception types to retry on
    
    Usage:
        @exponential_backoff_retry(max_retries=3, exception_types=(TimeoutError, ConnectionError))
        def call_external_api():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exception_types as exc:
                    last_exception = exc
                    
                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {exc}"
                        )
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay_ms = min(
                        initial_delay_ms * (2 ** attempt),
                        max_delay_ms,
                    )
                    
                    # Add jitter (±10%)
                    if jitter:
                        jitter_factor = 1 + random.uniform(-0.1, 0.1)
                        delay_ms = int(delay_ms * jitter_factor)
                    
                    delay_seconds = delay_ms / 1000.0
                    logger.debug(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed "
                        f"({exc.__class__.__name__}), retrying in {delay_seconds:.2f}s"
                    )
                    time.sleep(delay_seconds)
            
            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator
