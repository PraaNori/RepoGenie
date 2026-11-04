import logging
import threading
from typing import Dict, List, Optional

from .schemas import TokenUsageRecord, TokenUsageSummary

logger = logging.getLogger(__name__)


class TokenTracker:
    """
    Thread-safe in-memory token usage tracker.
    Records actual vs estimated token metrics across all AI operations and jobs.
    """

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history
        self._records: List[TokenUsageRecord] = []
        self._lock = threading.Lock()

    def record_usage(self, record: TokenUsageRecord) -> None:
        """
        Appends a token usage record to the history.
        """
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_history:
                # Retain the most recent records
                self._records = self._records[-self._max_history:]

        logger.debug(
            "Recorded token usage: provider=%s, model=%s, total=%d (estimated=%s, op=%s, job=%s)",
            record.provider,
            record.model,
            record.total_tokens,
            record.is_estimated,
            record.operation,
            record.job_id,
        )

    def get_summary(self) -> TokenUsageSummary:
        """
        Computes aggregate token usage statistics across all recorded requests.
        """
        with self._lock:
            records = list(self._records)

        summary = TokenUsageSummary()
        summary.total_requests = len(records)

        by_provider: Dict[str, int] = {}
        by_model: Dict[str, int] = {}

        for rec in records:
            summary.total_tokens += rec.total_tokens
            summary.total_prompt_tokens += rec.prompt_tokens
            summary.total_completion_tokens += rec.completion_tokens
            if rec.is_estimated:
                summary.estimated_requests_count += 1

            by_provider[rec.provider] = by_provider.get(rec.provider, 0) + rec.total_tokens
            by_model[rec.model] = by_model.get(rec.model, 0) + rec.total_tokens

        summary.by_provider = by_provider
        summary.by_model = by_model
        return summary

    def get_recent_records(self, limit: int = 50) -> List[TokenUsageRecord]:
        """
        Returns the most recent token usage records up to limit.
        """
        with self._lock:
            return list(reversed(self._records[-limit:]))

    def get_job_tokens(self, job_id: str) -> int:
        """
        Computes total tokens used for a specific job_id.
        """
        with self._lock:
            return sum(r.total_tokens for r in self._records if r.job_id == job_id)

    def get_job_records(self, job_id: str) -> List[TokenUsageRecord]:
        """
        Returns all token records for a given job_id.
        """
        with self._lock:
            return [r for r in self._records if r.job_id == job_id]

    def reset(self) -> None:
        """
        Clears all in-memory usage records (useful for test isolation).
        """
        with self._lock:
            self._records.clear()


token_tracker = TokenTracker()
