"""Enkel in-memory rate limiter for AI-mekaniker.

For MVP — telles per måned per device_id. Resettes ved redeploy
(akseptabel begrensning før vi har en database).
"""
from datetime import datetime, timezone


class _RateLimiter:
    FREE_LIMIT_PER_MONTH = 3

    def __init__(self) -> None:
        # {device_id: {"YYYY-MM": count}}
        self._counts: dict[str, dict[str, int]] = {}

    def _month_key(self) -> str:
        now = datetime.now(timezone.utc)
        return f"{now.year:04d}-{now.month:02d}"

    def get_count(self, device_id: str) -> int:
        month = self._month_key()
        return self._counts.get(device_id, {}).get(month, 0)

    def remaining(self, device_id: str) -> int:
        used = self.get_count(device_id)
        return max(0, self.FREE_LIMIT_PER_MONTH - used)

    def can_use(self, device_id: str) -> bool:
        return self.get_count(device_id) < self.FREE_LIMIT_PER_MONTH

    def increment(self, device_id: str) -> None:
        month = self._month_key()
        if device_id not in self._counts:
            self._counts[device_id] = {}
        self._counts[device_id][month] = self._counts[device_id].get(month, 0) + 1


chat_rate_limiter = _RateLimiter()


class _ScanRateLimiter(_RateLimiter):
    """Egen limiter for kvittering-skanning. Free brukere får 5 OCR per måned."""

    FREE_LIMIT_PER_MONTH = 5


scan_rate_limiter = _ScanRateLimiter()
