"""Metrics system for evaluating translation quality."""

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any, Optional


@dataclass
class MetricResult:
    """Result from a metric evaluation."""
    metric_name: str
    value: float
    passed: bool
    details: Optional[dict[str, Any]] = None


# Type alias for metric functions
MetricFunction = Callable[[Path, str, dict], MetricResult]

# Registry of all available metrics
_METRICS_REGISTRY: dict[str, MetricFunction] = {}

# Flag to track if auto-discovery has been run
_AUTO_DISCOVERY_DONE = False


def metric(name: str):
    """Decorator to register a metric function.

    Example:
        @metric("word_accuracy")
        def word_accuracy_metric(input_audio: Path, expected_text: str, received_data: dict) -> MetricResult:
            # Calculate accuracy
            return MetricResult(metric_name="word_accuracy", value=0.95, passed=True)
    """
    def decorator(func: MetricFunction) -> MetricFunction:
        _METRICS_REGISTRY[name] = func
        return func
    return decorator


def _auto_discover_metrics():
    """Automatically discover and import all metric modules in the metrics package.

    This function recursively finds all Python modules in the metrics directory
    and its subdirectories, importing them to trigger @metric decorator registration.
    """
    global _AUTO_DISCOVERY_DONE

    if _AUTO_DISCOVERY_DONE:
        return

    # Get the metrics package path
    metrics_package = Path(__file__).parent

    # Find all .py files in metrics directory and subdirectories
    for py_file in metrics_package.rglob("*.py"):
        # Skip __init__.py and this file
        if py_file.name in ("__init__.py", "__pycache__"):
            continue

        # Calculate module path relative to metrics package
        relative_path = py_file.relative_to(metrics_package.parent)

        # Convert path to module name: metrics/text_metrics.py -> metrics.text_metrics
        module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
        module_name = ".".join(module_parts)

        try:
            # Import the module to trigger @metric decorator
            importlib.import_module(module_name)
        except Exception as e:
            # Print warning but don't fail - allow other metrics to load
            print(f"Warning: Failed to import metric module {module_name}: {e}")

    _AUTO_DISCOVERY_DONE = True


def get_all_metrics() -> dict[str, MetricFunction]:
    """Get all registered metrics.

    Automatically discovers and imports all metric modules on first call.

    Returns:
        Dictionary mapping metric names to metric functions
    """
    _auto_discover_metrics()
    return _METRICS_REGISTRY.copy()


def get_metric(name: str) -> Optional[MetricFunction]:
    """Get a specific metric by name.

    Automatically discovers and imports all metric modules on first call.

    Args:
        name: Metric name

    Returns:
        Metric function or None if not found
    """
    _auto_discover_metrics()
    return _METRICS_REGISTRY.get(name)
