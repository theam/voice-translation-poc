from __future__ import annotations

from typing import Any, Dict, Mapping


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """Recursively merge two mappings.
    - Dicts are merged
    - All other values (including lists) are replaced
    """
    result: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

