"""WebSocket wrapper with JSON payload logging.

This module provides a wrapper class that logs all JSON messages sent and received
through a WebSocket connection. Useful for debugging and analyzing WebSocket communication.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


class WebSocketLogger:
    """
    WebSocket wrapper that logs all JSON payloads to a file.

    This class wraps a WebSocket connection and intercepts all send/receive operations,
    logging JSON payloads to a file for debugging and analysis purposes.

    Usage:
        # Basic send/receive
        async with websockets.connect(url) as ws:
            logged_ws = WebSocketLogger(ws, log_file="sent_messages.log")
            await logged_ws.send(json.dumps({"type": "test"}))
            response = await logged_ws.recv()

        # Async iteration
        async with websockets.connect(url) as ws:
            logged_ws = WebSocketLogger(ws, log_file="messages.log")
            async for message in logged_ws:
                process(message)

    Attributes:
        websocket: The underlying WebSocket connection
        log_file: Path to the log file
        message_count: Counter for sent messages
        receive_count: Counter for received messages
    """

    def __init__(
        self,
        websocket: Any,
        log_file: Union[str, Path] = "sent_messages.log",
        log_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        """
        Initialize the WebSocket logger.

        Args:
            websocket: The WebSocket connection to wrap
            log_file: Name of the log file (default: "sent_messages.log")
            log_dir: Directory for log file. If None, uses current directory.
        """
        self.websocket = websocket
        self.message_count = 0
        self.receive_count = 0

        # Set up log file path
        if log_dir:
            log_path = Path(log_dir) / log_file
            log_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            log_path = Path(log_file)

        self.log_file = log_path

        # Create/clear log file with header
        with open(self.log_file, "w") as f:
            f.write("=" * 80 + "\n")
            f.write(f"WebSocket Communication Log - Started at {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n\n")

        logger.info(f"WebSocket logging initialized: {self.log_file}")

    async def send(self, message: Union[str, bytes]) -> None:
        """
        Send a message through the WebSocket and log it.

        Args:
            message: The message to send (string or bytes)
        """
        # Log the outgoing message
        self._log_message("SENDING", message)

        # Send through underlying websocket
        await self.websocket.send(message)

    async def recv(self) -> Union[str, bytes]:
        """
        Receive a message from the WebSocket and log it.

        Returns:
            The received message (string or bytes)
        """
        # Receive from underlying websocket
        message = await self.websocket.recv()

        # Log the incoming message
        self._log_message("RECV", message)

        return message

    def __aiter__(self):
        """
        Return self as an async iterator.

        This enables usage like:
            async for message in websocket_logger:
                process(message)
        """
        return self

    async def __anext__(self) -> Union[str, bytes]:
        """
        Get the next message from the WebSocket.

        This method is called by async for loops. It receives and logs
        the message, then returns it. Raises StopAsyncIteration when
        the connection closes.

        Returns:
            The next received message (string or bytes)

        Raises:
            StopAsyncIteration: When the WebSocket connection is closed
        """
        try:
            # Use recv which already handles logging
            return await self.recv()
        except Exception:
            # Connection closed or error - stop iteration
            raise StopAsyncIteration

    def _log_message(self, direction: str, message: Union[str, bytes]) -> None:
        """
        Log a message to the log file with formatting.

        Args:
            direction: "SENT" or "RECV"
            message: The message to log
        """
        timestamp = datetime.now().isoformat()

        # Increment appropriate counter
        if direction == "SENT":
            self.message_count += 1
            count = self.message_count
        else:
            self.receive_count += 1
            count = self.receive_count

        # Prepare log entry
        separator = "-" * 80
        header = f"\n{separator}\n[{timestamp}] {direction} #{count}\n{separator}\n"

        # Try to parse and pretty-print JSON
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
                formatted_message = json.dumps(parsed, indent=2)
                message_type = parsed.get("type", parsed.get("kind", "unknown"))
                header += f"Type: {message_type}\n{separator}\n"
            except (json.JSONDecodeError, ValueError):
                # Not JSON, log as-is
                formatted_message = message
        elif isinstance(message, bytes):
            # Try to decode bytes as JSON
            try:
                decoded = message.decode("utf-8")
                parsed = json.loads(decoded)
                formatted_message = json.dumps(parsed, indent=2)
                message_type = parsed.get("type", parsed.get("kind", "unknown"))
                header += f"Type: {message_type}\n{separator}\n"
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                # Binary data, log size
                formatted_message = f"<binary data: {len(message)} bytes>"
        else:
            formatted_message = str(message)

        # Write to log file
        try:
            with open(self.log_file, "a") as f:
                f.write(header)
                f.write(formatted_message)
                f.write("\n")
        except Exception as e:
            logger.error(f"Failed to write to log file {self.log_file}: {e}")

    def close_log(self) -> None:
        """
        Write a footer to the log file and close logging.

        Note: Does not close the underlying WebSocket connection.
        """
        timestamp = datetime.now().isoformat()
        footer = (
            f"\n\n{'=' * 80}\n"
            f"WebSocket Communication Log - Ended at {timestamp}\n"
            f"Total Messages Sent: {self.message_count}\n"
            f"Total Messages Received: {self.receive_count}\n"
            f"{'=' * 80}\n"
        )

        try:
            with open(self.log_file, "a") as f:
                f.write(footer)
        except Exception as e:
            logger.error(f"Failed to write footer to log file {self.log_file}: {e}")

        logger.info(
            f"WebSocket logging closed: {self.message_count} sent, "
            f"{self.receive_count} received"
        )

    # Proxy other WebSocket attributes/methods
    def __getattr__(self, name: str) -> Any:
        """
        Proxy all other attribute access to the underlying WebSocket.

        This allows the wrapper to be used transparently in place of the
        original WebSocket object for methods we don't explicitly override.

        Args:
            name: The attribute name

        Returns:
            The attribute from the underlying WebSocket
        """
        return getattr(self.websocket, name)

    async def __aenter__(self):
        """Context manager entry - returns self for use in async with."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - closes log and underlying WebSocket."""
        self.close_log()
        if hasattr(self.websocket, "__aexit__"):
            return await self.websocket.__aexit__(exc_type, exc_val, exc_tb)

    def __repr__(self) -> str:
        """String representation of the logger."""
        return (
            f"WebSocketLogger(log_file={self.log_file}, "
            f"sent={self.message_count}, recv={self.receive_count})"
        )