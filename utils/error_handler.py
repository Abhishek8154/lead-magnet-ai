import os
import sys
import time
import traceback
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Any, Optional, Tuple, Dict
from utils.logger import get_logger

logger = get_logger("ErrorHandler")

ERRORS_LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "errors.log"


class ErrorCategory(str, Enum):
    TRANSIENT = "TRANSIENT"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH_ERROR = "AUTH_ERROR"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    PERMANENT = "PERMANENT"
    UNKNOWN = "UNKNOWN"


class QuotaExceededError(Exception):
    """Raised when API quota is exhausted and the batch must stop immediately."""
    pass


class AuthError(Exception):
    """Raised when authentication fails and execution must stop immediately."""
    pass


class SkipLeadError(Exception):
    """Raised when a lead has a permanent error and must be skipped."""
    pass


def classify_error(exception: Exception) -> Tuple[ErrorCategory, Optional[int]]:
    """
    Classifies an exception into one of the ErrorCategory enum values.
    Returns (ErrorCategory, retry_after_seconds_or_none).
    """
    exc_type_str = str(type(exception)).lower()
    msg = str(exception).lower()

    # Inspect HTTP response status code if available
    status_code = getattr(exception, "status_code", None)
    if not status_code and hasattr(exception, "response") and hasattr(exception.response, "status_code"):
        status_code = exception.response.status_code

    # Inspect Retry-After header if available
    retry_after = None
    if hasattr(exception, "response") and hasattr(exception.response, "headers"):
        headers = exception.response.headers
        if "Retry-After" in headers:
            try:
                retry_after = int(headers["Retry-After"])
            except ValueError:
                pass

    if status_code == 429 or "rate limit" in msg or "too many requests" in msg:
        if "quota" in msg or "exceeded" in msg or "insufficient_quota" in msg:
            return ErrorCategory.QUOTA_EXCEEDED, None
        return ErrorCategory.RATE_LIMIT, retry_after or 60

    if status_code in (401, 403) or "unauthorized" in msg or "invalid api key" in msg or "auth_error" in msg:
        return ErrorCategory.AUTH_ERROR, None

    if status_code == 404 or "not found" in msg:
        return ErrorCategory.NOT_FOUND, None

    if status_code and status_code >= 500 or "timeout" in msg or "connection error" in msg or "connect" in msg or "network" in msg:
        return ErrorCategory.TRANSIENT, None

    if "invalid" in msg or "missing" in msg or "malformed" in msg:
        return ErrorCategory.INVALID_INPUT, None

    if isinstance(exception, (ValueError, KeyError, TypeError)):
        return ErrorCategory.PERMANENT, None

    return ErrorCategory.UNKNOWN, None


def log_error(
    exception: Exception,
    lead_id: Optional[str] = None,
    module_name: str = "General",
    log_file: Optional[Path] = None
):
    """Logs detailed error info to errors.log file with timestamp, module name, and lead_id."""
    target_file = log_file or ERRORS_LOG_FILE
    os.makedirs(target_file.parent, exist_ok=True)

    category, _ = classify_error(exception)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lead_info = f" | LeadID: {lead_id}" if lead_id else ""

    log_entry = (
        f"[{now_str}] [{category.value}] [{module_name}]{lead_info}: {str(exception)}\n"
        f"Traceback:\n{traceback.format_exc()}\n"
        f"{'-'*80}\n"
    )

    try:
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"Failed writing to errors.log: {e}")

    logger.error(f"[{category.value}] [{module_name}]{lead_info}: {exception}")


def retry_with_backoff(
    func: Callable[..., Any],
    *args,
    max_retries: int = 3,
    base_delay: float = 2.0,
    lead_id: Optional[str] = None,
    module_name: str = "General",
    **kwargs
) -> Any:
    """
    Executes a function with error classification and exponential backoff retry logic:
    - TRANSIENT: Exponential backoff retry (2s, 4s, 8s)
    - RATE_LIMIT: Waits Retry-After header (or default), retries once
    - AUTH_ERROR: Stops immediately, logs error, raises AuthError
    - QUOTA_EXCEEDED: Stops batch immediately, raises QuotaExceededError
    - PERMANENT / INVALID_INPUT / NOT_FOUND: Logs error, raises SkipLeadError
    """
    attempt = 0
    while attempt <= max_retries:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            category, retry_after = classify_error(e)
            log_error(e, lead_id=lead_id, module_name=module_name)

            if category == ErrorCategory.AUTH_ERROR:
                err_msg = f"[AUTH ERROR] Fatal authentication failure in {module_name}: {e}. Stopping immediately."
                logger.error(err_msg)
                print(f"FATAL ERROR: {err_msg}")
                raise AuthError(err_msg) from e

            if category == ErrorCategory.QUOTA_EXCEEDED:
                err_msg = f"[QUOTA EXCEEDED] API quota exhausted in {module_name}: {e}. Stopping batch to preserve completed work."
                logger.error(err_msg)
                print(f"FATAL BATCH ERROR: {err_msg}")
                raise QuotaExceededError(err_msg) from e

            if category == ErrorCategory.RATE_LIMIT:
                wait_time = retry_after or 60
                logger.warning(f"[RATE LIMIT] Rate limited in {module_name}. Waiting {wait_time}s before single retry...")
                time.sleep(wait_time)
                try:
                    return func(*args, **kwargs)
                except Exception as retry_exc:
                    log_error(retry_exc, lead_id=lead_id, module_name=module_name)
                    raise

            if category in (ErrorCategory.PERMANENT, ErrorCategory.INVALID_INPUT, ErrorCategory.NOT_FOUND):
                logger.warning(f"[PERMANENT ERROR] Skipping lead {lead_id or ''} due to permanent error: {e}")
                raise SkipLeadError(f"Skipping lead due to {category.value}: {e}") from e

            # Handle TRANSIENT & UNKNOWN errors with exponential backoff
            attempt += 1
            if attempt > max_retries:
                logger.error(f"[MAX RETRIES EXCEEDED] Failed after {max_retries} attempts in {module_name}: {e}")
                raise

            delay = base_delay * (2 ** (attempt - 1))
            logger.info(f"[TRANSIENT ERROR] Attempt {attempt}/{max_retries} failed in {module_name}. Retrying in {delay}s...")
            time.sleep(delay)
