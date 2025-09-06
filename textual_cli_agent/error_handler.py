from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ErrorAnalysis:
    """Analysis of an API error and suggested recovery action."""

    error_type: str
    is_recoverable: bool
    should_retry: bool
    should_reduce_context: bool
    should_prune_messages: bool
    wait_seconds: Optional[float] = None
    recovery_message: str = ""


class APIErrorHandler:
    """Handles 4XX API errors with intelligent recovery strategies."""

    def __init__(self):
        self.retry_counts: Dict[str, int] = {}
        self.max_retries = 3

    def analyze_error(self, error: Exception) -> ErrorAnalysis:
        """Analyze an API error and determine recovery strategy."""
        error_str = str(error)
        error_lower = error_str.lower()

        # OpenAI rate limit (429)
        if "429" in error_str and "rate_limit_exceeded" in error_str:
            return self._analyze_rate_limit_error(error_str)

        # OpenAI token limit (400)
        if "400" in error_str and ("token" in error_lower or "context" in error_lower):
            return self._analyze_token_limit_error(error_str)

        # OpenAI context window exceeded
        if ("context" in error_lower and "window" in error_lower) or (
            "maximum context length" in error_lower
        ):
            return ErrorAnalysis(
                error_type="context_exceeded",
                is_recoverable=True,
                should_retry=True,
                should_reduce_context=True,
                should_prune_messages=True,
                recovery_message="Context window exceeded. Reducing message history and retrying...",
            )

        # Other 4XX client errors
        if any(
            code in error_str for code in ["400", "401", "403", "404", "422", "429"]
        ):
            if "401" in error_str:
                return ErrorAnalysis(
                    error_type="auth_error",
                    is_recoverable=False,
                    should_retry=False,
                    should_reduce_context=False,
                    should_prune_messages=False,
                    recovery_message="Authentication failed. Please check your API key.",
                )
            elif "403" in error_str:
                return ErrorAnalysis(
                    error_type="forbidden",
                    is_recoverable=False,
                    should_retry=False,
                    should_reduce_context=False,
                    should_prune_messages=False,
                    recovery_message="Access forbidden. Check API permissions or usage limits.",
                )
            elif "422" in error_str:
                return ErrorAnalysis(
                    error_type="validation_error",
                    is_recoverable=True,
                    should_retry=False,
                    should_reduce_context=True,
                    should_prune_messages=True,
                    recovery_message="Request validation failed. Attempting to fix request format...",
                )

        # 5XX server errors - should retry
        if any(code in error_str for code in ["500", "502", "503", "504"]):
            return ErrorAnalysis(
                error_type="server_error",
                is_recoverable=True,
                should_retry=True,
                should_reduce_context=False,
                should_prune_messages=False,
                wait_seconds=5.0,
                recovery_message="Server error encountered. Retrying in 5 seconds...",
            )

        # Network/timeout errors
        if any(term in error_lower for term in ["timeout", "connection", "network"]):
            return ErrorAnalysis(
                error_type="network_error",
                is_recoverable=True,
                should_retry=True,
                should_reduce_context=False,
                should_prune_messages=False,
                wait_seconds=2.0,
                recovery_message="Network error. Retrying in 2 seconds...",
            )

        # Default for unknown errors
        return ErrorAnalysis(
            error_type="unknown",
            is_recoverable=False,
            should_retry=False,
            should_reduce_context=False,
            should_prune_messages=False,
            recovery_message=f"Unknown error: {error_str}",
        )

    def _analyze_rate_limit_error(self, error_str: str) -> ErrorAnalysis:
        """Analyze rate limit errors and extract wait time."""
        wait_seconds = 60.0  # Default wait

        # Try to extract wait time from error message
        # Look for patterns like "Try again in 20s" or "Limit: 30000, Requested: 30992"
        time_match = re.search(r"try again in (\d+)s", error_str.lower())
        if time_match:
            wait_seconds = float(time_match.group(1))
        else:
            # Look for RPM (requests per minute) or TPM (tokens per minute) limits
            if "tpm" in error_str.lower() or "tokens per min" in error_str.lower():
                wait_seconds = 20.0  # Wait 20 seconds for token limits
            elif "rpm" in error_str.lower() or "requests per min" in error_str.lower():
                wait_seconds = 60.0  # Wait 1 minute for request limits

        return ErrorAnalysis(
            error_type="rate_limit",
            is_recoverable=True,
            should_retry=True,
            should_reduce_context="tpm" in error_str.lower()
            or "tokens" in error_str.lower(),
            should_prune_messages="tpm" in error_str.lower()
            or "tokens" in error_str.lower(),
            wait_seconds=wait_seconds,
            recovery_message=f"Rate limit exceeded. Waiting {wait_seconds}s before retrying...",
        )

    def _analyze_token_limit_error(self, error_str: str) -> ErrorAnalysis:
        """Analyze token limit errors."""
        return ErrorAnalysis(
            error_type="token_limit",
            is_recoverable=True,
            should_retry=True,
            should_reduce_context=True,
            should_prune_messages=True,
            recovery_message="Token limit exceeded. Reducing conversation history and retrying...",
        )

    async def handle_error_with_retry(
        self, error: Exception, retry_key: str, retry_func, *args, **kwargs
    ):
        """Handle an error with intelligent retry logic."""
        analysis = self.analyze_error(error)

        if not analysis.is_recoverable:
            logger.error(f"Non-recoverable error: {analysis.recovery_message}")
            raise error

        retry_count = self.retry_counts.get(retry_key, 0)
        if retry_count >= self.max_retries:
            logger.error(f"Max retries ({self.max_retries}) exceeded for {retry_key}")
            raise error

        if not analysis.should_retry:
            logger.error(f"Error should not be retried: {analysis.recovery_message}")
            raise error

        self.retry_counts[retry_key] = retry_count + 1
        logger.info(
            f"Attempting retry {retry_count + 1}/{self.max_retries} for {retry_key}: {analysis.recovery_message}"
        )

        if analysis.wait_seconds:
            await asyncio.sleep(analysis.wait_seconds)

        async for chunk in retry_func(*args, **kwargs):
            yield chunk

    def reset_retry_count(self, retry_key: str) -> None:
        """Reset retry count for successful operations."""
        if retry_key in self.retry_counts:
            del self.retry_counts[retry_key]

    def should_prune_context(self, error: Exception) -> bool:
        """Check if context should be pruned for this error."""
        analysis = self.analyze_error(error)
        return analysis.should_prune_messages

    def get_recovery_message(self, error: Exception) -> str:
        """Get user-friendly recovery message."""
        analysis = self.analyze_error(error)
        return analysis.recovery_message


# Global error handler instance
api_error_handler = APIErrorHandler()
