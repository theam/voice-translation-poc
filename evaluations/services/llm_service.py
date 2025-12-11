"""OpenAI LLM client for evaluation metrics.

This module provides a simple interface to call OpenAI APIs.
Individual metrics implement their own prompts and logic.
"""

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any
import json


@dataclass
class LLMResponse:
    """Response from OpenAI API."""
    content: str
    raw_response: Optional[Dict[str, Any]] = None
    tokens_used: Optional[int] = None
    model: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    def as_json(self) -> Optional[Dict[str, Any]]:
        """Parse response content as JSON.

        Returns:
            Parsed JSON dict or None if parsing fails
        """
        if not self.success:
            return None

        try:
            return json.loads(self.content)
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse LLM JSON response: {e}")
            print(f"Response content: {self.content}")
            return None


class LLMService:
    """OpenAI client for making LLM API calls.

    Simple wrapper that handles OpenAI authentication and calls.
    Each metric implements its own prompts and response parsing logic.

    Example:
        >>> llm = LLMService()
        >>> response = llm.call(
        ...     prompt="What is 2+2?",
        ...     system_prompt="You are a calculator"
        ... )
        >>> print(response.content)  # "4"
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ):
        """Initialize OpenAI LLM service.

        Args:
            model: OpenAI model name (default: gpt-4o-mini for cost-effectiveness)
            api_key: OpenAI API key (defaults to AZURE_AI_FOUNDRY_KEY env var)
            temperature: Sampling temperature (0-1, lower = more deterministic)
            max_tokens: Maximum tokens in response (None = no limit)
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv("AZURE_AI_FOUNDRY_KEY")

        # Base URL for the OpenAI client.
        # Default to the Azure-hosted endpoint, but allow override via env.
        self.base_url = os.getenv(
            "OPENAI_BASE_URL",
        )

        # Lazy-load client
        self._client = None

    def _get_client(self):
        """Lazy-load the OpenAI client."""
        if self._client is not None:
            return self._client

        try:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                api_version="2024-10-01-preview",
                api_key=self.api_key,
                azure_endpoint=self.base_url,
            )
            return self._client
        except ImportError:
            raise RuntimeError(
                "OpenAI library not installed. Install with: pip install openai"
            )

    def call(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_format: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Make an OpenAI API call.

        Args:
            prompt: User prompt
            system_prompt: System instructions (optional)
            response_format: Expected format ("json" or None)
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            LLMResponse with content and metadata
        """
        if not self.api_key:
            return LLMResponse(
                content="",
                error="OpenAI API key not configured. Set AZURE_AI_FOUNDRY_KEY environment variable."
            )

        try:
            client = self._get_client()

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Build API call parameters
            params = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature if temperature is not None else self.temperature,
            }

            # Add max_tokens if specified
            if max_tokens is not None or self.max_tokens is not None:
                params["max_tokens"] = max_tokens if max_tokens is not None else self.max_tokens

            # Add response format if requested
            if response_format == "json":
                params["response_format"] = {"type": "json_object"}

            # Call OpenAI API
            response = client.chat.completions.create(**params)
            content = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else None

            return LLMResponse(
                content=content,
                raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
                tokens_used=tokens_used,
                model=self.model,
            )

        except Exception as e:
            return LLMResponse(
                content="",
                error=f"OpenAI API call failed: {str(e)}"
            )


# Global singleton for easy access
_default_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get or create the default LLM service instance.

    Returns:
        Shared LLMService instance
    """
    global _default_service
    if _default_service is None:
        _default_service = LLMService()
    return _default_service
