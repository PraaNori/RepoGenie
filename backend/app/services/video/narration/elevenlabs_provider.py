"""
ElevenLabs Text-to-Speech Provider Integration (Milestone 5, Phase 5.4).

Provides asynchronous, retry-resilient speech synthesis against the official ElevenLabs API.
Enforces strict secret masking, bounded retries with exponential backoff for transient failures,
and immediate fail-fast semantics for permanent configuration or authentication errors.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class ElevenLabsError(Exception):
    """Base exception for all ElevenLabs TTS operations."""
    pass


class ElevenLabsConfigurationError(ElevenLabsError):
    """Raised when required credentials or voice configurations are missing."""
    pass


class ElevenLabsAuthError(ElevenLabsError):
    """Raised when authentication fails (HTTP 401 / 403). Permanent: do not retry."""
    pass


class ElevenLabsVoiceNotFoundError(ElevenLabsError):
    """Raised when the specified Voice ID does not exist (HTTP 404). Permanent: do not retry."""
    pass


class ElevenLabsBadRequestError(ElevenLabsError):
    """Raised on invalid request parameters or unsupported model (HTTP 400). Permanent: do not retry."""
    pass


class ElevenLabsRateLimitError(ElevenLabsError):
    """Raised when ElevenLabs rate limits are exceeded (HTTP 429). Transient: retryable."""
    pass


class ElevenLabsTimeoutError(ElevenLabsError):
    """Raised when an API request times out. Transient: retryable."""
    pass


class ElevenLabsServerError(ElevenLabsError):
    """Raised when ElevenLabs returns a 5xx server error. Transient: retryable."""
    pass


# ---------------------------------------------------------------------------
# Provider Class
# ---------------------------------------------------------------------------

class ElevenLabsTTSProvider:
    """
    Asynchronous ElevenLabs Text-to-Speech API client.
    Handles synthesis, transient retries, error classification, and secret safety.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        output_format: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        self._api_key = api_key if api_key is not None else settings.ELEVENLABS_API_KEY
        self._voice_id = voice_id if voice_id is not None else settings.ELEVENLABS_VOICE_ID
        self._model_id = model_id or settings.ELEVENLABS_MODEL_ID
        self._output_format = output_format or settings.ELEVENLABS_OUTPUT_FORMAT
        self._timeout = timeout or settings.ELEVENLABS_TIMEOUT
        self._max_retries = max_retries if max_retries is not None else settings.ELEVENLABS_MAX_RETRIES

    @property
    def is_configured(self) -> bool:
        """Returns True only if both API key and Voice ID are populated."""
        return bool(self._api_key and self._api_key.strip() and self._voice_id and self._voice_id.strip())

    @property
    def voice_id(self) -> Optional[str]:
        return self._voice_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def output_format(self) -> str:
        return self._output_format

    def validate_configuration(self) -> None:
        """Validates that necessary credentials and voice IDs are configured."""
        if not self._api_key or not self._api_key.strip():
            raise ElevenLabsConfigurationError(
                "ElevenLabs API key is missing. Set ELEVENLABS_API_KEY in backend/.env."
            )
        if not self._voice_id or not self._voice_id.strip():
            raise ElevenLabsConfigurationError(
                "ElevenLabs Voice ID is missing. Set ELEVENLABS_VOICE_ID in backend/.env."
            )

    async def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> bytes:
        """
        Synthesizes spoken narration audio for the given text.

        Retries on transient errors (429, 5xx, network timeouts).
        Fails fast on permanent errors (401, 403, 404, 400).
        """
        self.validate_configuration()

        clean_text = text.strip() if text else ""
        if not clean_text:
            raise ValueError("Cannot synthesize audio for empty narration text.")

        active_voice = (voice_id or self._voice_id or "").strip()
        active_model = (model_id or self._model_id or "").strip()

        url = f"{ELEVENLABS_API_BASE}/text-to-speech/{active_voice}"
        params = {"output_format": self._output_format}
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": clean_text,
            "model_id": active_model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        # Safe client management
        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            close_client = True

        last_exception: Optional[Exception] = None

        try:
            for attempt in range(self._max_retries + 1):
                try:
                    logger.debug(
                        "ElevenLabs synthesis request: voice=%s model=%s chars=%d attempt=%d/%d",
                        active_voice,
                        active_model,
                        len(clean_text),
                        attempt + 1,
                        self._max_retries + 1,
                    )
                    response = await client.post(
                        url,
                        params=params,
                        headers=headers,
                        json=payload,
                    )

                    # 1. Success response (200 OK)
                    if response.status_code == 200:
                        content = response.content
                        if not content or len(content) < 16:
                            raise ElevenLabsError(
                                f"ElevenLabs returned empty or truncated audio response ({len(content)} bytes)."
                            )
                        return content

                    # 2. Permanent errors: fail immediately without retrying
                    if response.status_code in (401, 403):
                        err_msg = self._extract_error_detail(response)
                        logger.error("ElevenLabs authentication failure: %s", err_msg)
                        raise ElevenLabsAuthError(f"ElevenLabs authentication failed (HTTP {response.status_code}): {err_msg}")

                    if response.status_code == 404:
                        err_msg = self._extract_error_detail(response)
                        logger.error("ElevenLabs voice not found: %s", err_msg)
                        raise ElevenLabsVoiceNotFoundError(f"ElevenLabs voice '{active_voice}' not found: {err_msg}")

                    if response.status_code == 400:
                        err_msg = self._extract_error_detail(response)
                        logger.error("ElevenLabs bad request: %s", err_msg)
                        raise ElevenLabsBadRequestError(f"ElevenLabs bad request: {err_msg}")

                    # 3. Transient errors: retry with backoff
                    if response.status_code == 429:
                        err_msg = self._extract_error_detail(response)
                        logger.warning("ElevenLabs rate limit encountered on attempt %d: %s", attempt + 1, err_msg)
                        if attempt == self._max_retries:
                            raise ElevenLabsRateLimitError(f"ElevenLabs rate limit exceeded: {err_msg}")
                        last_exception = ElevenLabsRateLimitError(err_msg)

                    elif response.status_code >= 500:
                        err_msg = self._extract_error_detail(response)
                        logger.warning("ElevenLabs server error (HTTP %d) on attempt %d: %s", response.status_code, attempt + 1, err_msg)
                        if attempt == self._max_retries:
                            raise ElevenLabsServerError(f"ElevenLabs server error (HTTP {response.status_code}): {err_msg}")
                        last_exception = ElevenLabsServerError(err_msg)

                    else:
                        err_msg = self._extract_error_detail(response)
                        raise ElevenLabsError(f"ElevenLabs API error (HTTP {response.status_code}): {err_msg}")

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    logger.warning("Network/Timeout error during ElevenLabs synthesis (attempt %d): %s", attempt + 1, net_err)
                    if attempt == self._max_retries:
                        raise ElevenLabsTimeoutError(f"ElevenLabs request timed out after {self._max_retries + 1} attempts: {net_err}") from net_err
                    last_exception = net_err

                # Exponential backoff with bounded sleep
                sleep_seconds = min(0.5 * (2 ** attempt), 4.0)
                await asyncio.sleep(sleep_seconds)

            if last_exception:
                raise last_exception
            raise ElevenLabsError("ElevenLabs synthesis failed after exhausting maximum retries.")

        finally:
            if close_client:
                await client.aclose()

    async def test_connectivity(self) -> Dict[str, Any]:
        """
        Tests API key and voice configuration by retrieving voice details from ElevenLabs.
        Returns voice metadata dict or raises an ElevenLabsError.
        """
        self.validate_configuration()
        url = f"{ELEVENLABS_API_BASE}/voices/{self._voice_id}"
        headers = {"xi-api-key": self._api_key}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "status": "connected",
                        "voice_id": self._voice_id,
                        "voice_name": data.get("name", "Unknown"),
                        "category": data.get("category", "premade"),
                        "model_id": self._model_id,
                    }
                elif resp.status_code in (401, 403):
                    raise ElevenLabsAuthError(f"Invalid ElevenLabs credentials (HTTP {resp.status_code})")
                elif resp.status_code == 404:
                    raise ElevenLabsVoiceNotFoundError(f"Configured voice ID '{self._voice_id}' not found on ElevenLabs")
                else:
                    raise ElevenLabsError(f"ElevenLabs connectivity check failed: HTTP {resp.status_code}")
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                raise ElevenLabsTimeoutError(f"Network failure connecting to ElevenLabs: {e}") from e

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        """Safely extracts error message from ElevenLabs response without leaking secrets."""
        try:
            data = response.json()
            if isinstance(data, dict):
                detail = data.get("detail")
                if isinstance(detail, dict):
                    return detail.get("message", str(detail))
                if isinstance(detail, str):
                    return detail
                if "message" in data:
                    return str(data["message"])
            return response.text[:200]
        except Exception:
            return response.text[:200] if response.text else f"Status code {response.status_code}"


# Default singleton provider instance
elevenlabs_provider = ElevenLabsTTSProvider()
