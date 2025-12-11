"""Remote debugging utilities for PyCharm/IntelliJ."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import FrameworkConfig

logger = logging.getLogger(__name__)


def setup_remote_debugging(config: FrameworkConfig) -> bool:
    """
    Set up PyCharm remote debugging if enabled in configuration.

    This function conditionally imports and configures pydevd_pycharm for remote
    debugging. It's designed to fail gracefully if the debugging library is not
    available or if debugging is disabled.

    The remote debugging configuration is read from the FrameworkConfig object,
    which loads values from environment variables:
    - TRANSLATION_REMOTE_DEBUG: Set to "true" to enable (default: "false")
    - TRANSLATION_DEBUG_HOST: Remote debug server host (default: "localhost")
    - TRANSLATION_DEBUG_PORT: Remote debug server port (default: "5678")
    - TRANSLATION_DEBUG_SUSPEND: Wait for debugger to attach (default: "false")
    - TRANSLATION_DEBUG_STDOUT: Redirect stdout to debugger (default: "true")
    - TRANSLATION_DEBUG_STDERR: Redirect stderr to debugger (default: "true")

    Args:
        config: Framework configuration object containing debug settings

    Returns:
        True if debugging was successfully enabled, False otherwise

    Example:
        from utils.config import load_config
        from utils.debug import setup_remote_debugging

        config = load_config()
        if setup_remote_debugging(config):
            print("Remote debugging active")
    """
    # Check if remote debugging is enabled
    if not config.remote_debug:
        logger.debug("Remote debugging disabled (config.remote_debug = False)")
        return False

    # Get debug server configuration from config
    debug_host = config.debug_host
    debug_port = config.debug_port
    debug_suspend = config.debug_suspend
    debug_stdout = config.debug_stdout
    debug_stderr = config.debug_stderr

    try:
        # Import PyCharm debugger (pydevd_pycharm)
        import pydevd_pycharm

        logger.info(
            f"Connecting to PyCharm debug server at {debug_host}:{debug_port} "
            f"(suspend={debug_suspend})"
        )

        # Establish connection to the debug server
        pydevd_pycharm.settrace(
            host=debug_host,
            port=debug_port,
            stdout_to_server=debug_stdout,
            stderr_to_server=debug_stderr,
            suspend=debug_suspend,
            # The path mapping is handled by the IDE configuration
        )

        logger.info("✓ Remote debugging enabled successfully")
        return True

    except ImportError:
        logger.warning(
            "pydevd_pycharm not available - remote debugging disabled. "
            "Install with: pip install pydevd-pycharm"
        )
        return False

    except Exception as e:
        logger.error(f"Failed to enable remote debugging: {e}")
        logger.error(
            f"Make sure PyCharm/IntelliJ is running with a Python Debug Server "
            f"listening on {debug_host}:{debug_port}"
        )
        return False


def is_debugging_enabled() -> bool:
    """
    Check if remote debugging is currently enabled.

    This is a lightweight check that only looks at environment variables
    without attempting to import or connect to the debugger.

    Returns:
        True if TRANSLATION_REMOTE_DEBUG is set to "true", False otherwise
    """
    return os.getenv("TRANSLATION_REMOTE_DEBUG", "false").lower() == "true"
