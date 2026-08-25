import time
from collections import deque
from config import config
from utils.logger import get_logger

logger = get_logger("RateLimiter")


class RateLimiter:
    """Tracks and enforces hourly rate limits for Email and WhatsApp outreach dispatches."""

    def __init__(
        self,
        max_emails_per_hour: int = None,
        max_whatsapp_per_hour: int = None
    ):
        self.max_emails = max_emails_per_hour or config.MAX_EMAILS_PER_HOUR
        self.max_whatsapp = max_whatsapp_per_hour or config.MAX_WHATSAPP_PER_HOUR

        # Deques storing epoch timestamps of dispatches in past 3600 seconds
        self.email_timestamps = deque()
        self.whatsapp_timestamps = deque()

    def _purge_old_timestamps(self, timestamp_deque: deque, window_seconds: float = 3600.0):
        """Purges timestamps older than 3600 seconds from deque."""
        now = time.time()
        while timestamp_deque and (now - timestamp_deque[0]) > window_seconds:
            timestamp_deque.popleft()

    def can_send_email(self) -> bool:
        """Checks if email dispatch is allowed under max_emails_per_hour limit."""
        self._purge_old_timestamps(self.email_timestamps)
        if len(self.email_timestamps) >= self.max_emails:
            logger.warning(
                f"[RATE LIMIT] Hourly email limit ({self.max_emails}/hr) reached. "
                f"Count in last hour: {len(self.email_timestamps)}"
            )
            return False
        return True

    def record_email_sent(self):
        """Records an email dispatch timestamp."""
        self.email_timestamps.append(time.time())
        logger.info(f"[RATE LIMIT] Email sent recorded. Current hourly count: {len(self.email_timestamps)}/{self.max_emails}")

    def can_send_whatsapp(self) -> bool:
        """Checks if WhatsApp dispatch is allowed under max_whatsapp_per_hour limit."""
        self._purge_old_timestamps(self.whatsapp_timestamps)
        if len(self.whatsapp_timestamps) >= self.max_whatsapp:
            logger.warning(
                f"[RATE LIMIT] Hourly WhatsApp limit ({self.max_whatsapp}/hr) reached. "
                f"Count in last hour: {len(self.whatsapp_timestamps)}"
            )
            return False
        return True

    def record_whatsapp_sent(self):
        """Records a WhatsApp dispatch timestamp."""
        self.whatsapp_timestamps.append(time.time())
        logger.info(f"[RATE LIMIT] WhatsApp sent recorded. Current hourly count: {len(self.whatsapp_timestamps)}/{self.max_whatsapp}")


# Global rate limiter singleton
rate_limiter = RateLimiter()
