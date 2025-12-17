"""Utility functions for metrics storage."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

try:
    import git
except ImportError:
    git = None  # type: ignore

logger = logging.getLogger(__name__)


def compute_config_hash(config: Dict[str, Any]) -> str:
    """Compute SHA-256 hash of configuration for quick comparison.

    The configuration is serialized to JSON with sorted keys to ensure
    consistent hashing regardless of key order.

    Args:
        config: Configuration dictionary

    Returns:
        Hex string of SHA-256 hash (64 characters)

    Example:
        >>> config = {"timeout": 5000, "endpoint": "https://api.example.com"}
        >>> hash1 = compute_config_hash(config)
        >>> hash2 = compute_config_hash({"endpoint": "https://api.example.com", "timeout": 5000})
        >>> hash1 == hash2  # True - order doesn't matter
    """
    # Sort keys for consistent hashing
    config_json = json.dumps(config, sort_keys=True)
    return hashlib.sha256(config_json.encode()).hexdigest()


def get_git_info() -> Tuple[Optional[str], Optional[str]]:
    """Get current git commit and branch information.

    Searches for a git repository starting from the current directory
    and walking up parent directories.

    Returns:
        Tuple of (commit_hash, branch_name)
        Returns (None, None) if:
        - Not in a git repository
        - GitPython is not installed
        - Git command fails

    Example:
        >>> commit, branch = get_git_info()
        >>> if commit:
        ...     print(f"Running on {branch} at {commit[:7]}")
    """
    if git is None:
        logger.info("GitPython not installed, git info unavailable")
        return None, None

    try:
        repo = git.Repo(search_parent_directories=True)

        # Get commit hash
        commit = repo.head.commit.hexsha

        # Get branch name (handle detached HEAD)
        if repo.head.is_detached:
            branch = None
            logger.debug("HEAD is detached, no branch info available")
        else:
            branch = repo.active_branch.name

        return commit, branch

    except git.InvalidGitRepositoryError:
        logger.info("Not in a git repository. Metrics will not store git information")
        return None, None
    except git.GitCommandError as e:
        logger.warning(f"Git command failed: {e}")
        return None, None
    except Exception as e:
        logger.warning(f"Unexpected error getting git info: {e}")
        return None, None


__all__ = ["compute_config_hash", "get_git_info"]
