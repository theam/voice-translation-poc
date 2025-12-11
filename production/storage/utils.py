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


def generate_evaluation_run_id(
    timestamp: datetime,
    git_commit: Optional[str] = None,
    git_branch: Optional[str] = None
) -> str:
    """Generate human-readable evaluation run ID.

    Creates a unique identifier combining timestamp, branch, and commit
    for easy identification of evaluation runs.

    Format:
        - With branch and commit: YYYY-MM-DDTHH-MM-SSZ-branch-commit
        - With commit only: YYYY-MM-DDTHH-MM-SSZ-commit
        - Without git info: YYYY-MM-DDTHH-MM-SSZ

    Args:
        timestamp: Start timestamp for the evaluation run
        git_commit: Optional git commit hash (first 6 chars used)
        git_branch: Optional git branch name

    Returns:
        Evaluation run ID string

    Examples:
        >>> from datetime import datetime
        >>> ts = datetime(2025, 12, 5, 10, 30, 0)
        >>> generate_evaluation_run_id(ts)
        '2025-12-05T10-30-00Z'
        >>>
        >>> generate_evaluation_run_id(ts, git_commit="abcdef123456")
        '2025-12-05T10-30-00Z-abcdef'
        >>>
        >>> generate_evaluation_run_id(ts, git_commit="abcdef123456", git_branch="main")
        '2025-12-05T10-30-00Z-main-abcdef'
    """
    # Format timestamp
    time_str = timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")

    # Build ID components
    parts = [time_str]

    if git_branch:
        # Sanitize branch name (replace / with -)
        safe_branch = git_branch.replace("/", "-")
        parts.append(safe_branch)

    if git_commit:
        # Use first 6 characters of commit hash
        commit_short = git_commit[:6]
        parts.append(commit_short)

    return "-".join(parts)


def generate_test_run_id(
    timestamp: datetime,
    test_id: str,
    evaluation_run_id: Optional[str] = None
) -> str:
    """Generate human-readable test run ID.

    Creates a unique identifier combining timestamp, test_id, and optional
    evaluation run ID for easy identification of individual test executions.

    Format:
        - With evaluation_run_id: YYYY-MM-DDTHH-MM-SSZ-test_id-eval_run_short
        - Without evaluation_run_id: YYYY-MM-DDTHH-MM-SSZ-test_id

    Args:
        timestamp: Start timestamp for the test run
        test_id: Test identifier (scenario.id)
        evaluation_run_id: Optional evaluation run ID (first 6 chars used)

    Returns:
        Test run ID string

    Examples:
        >>> from datetime import datetime
        >>> ts = datetime(2025, 12, 5, 10, 30, 0)
        >>> generate_test_run_id(ts, "test-001")
        '2025-12-05T10-30-00Z-test-001'
        >>>
        >>> generate_test_run_id(ts, "test-001", "2025-12-05T10-30-00Z-main-abcdef")
        '2025-12-05T10-30-00Z-test-001-202512'
    """
    # Format timestamp
    time_str = timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")

    # Build ID components
    parts = [time_str, test_id]

    if evaluation_run_id:
        # Use first 6 characters of evaluation run ID for brevity
        eval_run_short = evaluation_run_id[:6]
        parts.append(eval_run_short)

    return "-".join(parts)


__all__ = ["compute_config_hash", "get_git_info", "generate_evaluation_run_id", "generate_test_run_id"]
