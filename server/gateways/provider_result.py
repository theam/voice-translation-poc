"""Backward-compatible entrypoint for provider result handling."""

from .provider.provider_output_handler import ProviderOutputHandler as ProviderResultHandler

__all__ = ["ProviderResultHandler"]
