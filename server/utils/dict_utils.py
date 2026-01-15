from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def deep_merge(base: Mapping[str, Any], override: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Recursively merge two mappings.
    - Dicts are merged
    - All other values (including lists) are replaced
    - If override is None, returns a copy of base
    """
    result: Dict[str, Any] = dict(base)

    # Handle None override
    if override is None:
        return result

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def normalize_keys(data: Any) -> Any:
    """Recursively convert all dictionary keys to lowercase.

    This is useful for case-insensitive handling of data structures,
    such as normalizing incoming API payloads.

    Args:
        data: The data structure to normalize (dict, list, or primitive)

    Returns:
        A new data structure with all string keys converted to lowercase

    Examples:
        >>> normalize_keys({"Name": "Alice", "Age": 30})
        {'name': 'Alice', 'age': 30}

        >>> normalize_keys({"User": {"FirstName": "Bob"}})
        {'user': {'firstname': 'Bob'}}

        >>> normalize_keys([{"ID": 1}, {"ID": 2}])
        [{'id': 1}, {'id': 2}]
    """
    if isinstance(data, dict):
        return {
            k.lower() if isinstance(k, str) else k: normalize_keys(v)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [normalize_keys(item) for item in data]
    else:
        return data

