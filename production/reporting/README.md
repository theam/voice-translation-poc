# Production Reporting Module

Clean, database-driven PDF report generation service.

## Overview

The `production.reporting` module provides a streamlined API for generating comprehensive PDF evaluation reports directly from MongoDB data, with no dependencies on Scenario YAML files or live ConversationManager objects.

## Architecture

```
production/reporting/
├── __init__.py          # Public exports
├── models.py            # Data models (EvaluationRunData, TestReportData)
├── calibration_pdf_generator.py   # Calibration PDF generation
├── evaluation_pdf_generator.py    # Evaluation PDF generation
├── report_utils.py                # Shared helpers (colors, sanitization)
├── service.py                     # Main ReportingService API
└── README.md                      # This file
```

## Key Features

✅ **Database-Driven** - Generates reports entirely from MongoDB data
✅ **Clean API** - Single method to generate complete reports
✅ **No External Dependencies** - No need for Scenario YAML or ConversationManager
✅ **Historical Reports** - Generate reports anytime from stored data
✅ **Complete Data** - Includes metrics, turns, expected vs actual comparison

---

## Usage

### Basic Usage

```python
from bson import ObjectId
from production.storage import MongoDBClient, MetricsStorageService
from production.reporting import ReportingService

# Initialize storage
client = MongoDBClient("mongodb://localhost:27017", "vt_metrics")
storage_service = MetricsStorageService(client)

# Initialize reporting service
reporting_service = ReportingService(storage_service)

# Generate report from evaluation run ID
evaluation_run_id = ObjectId("507f1f77bcf86cd799439011")
report_path = await reporting_service.generate_evaluation_report(evaluation_run_id)

print(f"Report generated: {report_path}")
# Output: Report generated: /path/to/reports/evaluation_report_2024-12-12T10-30Z-abc.pdf
```

### Custom Output Directory

```python
from pathlib import Path

# Specify custom output directory
custom_dir = Path("/path/to/custom/reports")
reporting_service = ReportingService(storage_service, output_dir=custom_dir)

report_path = await reporting_service.generate_evaluation_report(evaluation_run_id)
# PDF will be saved to /path/to/custom/reports/
```

### CLI Integration Example

```python
# Example CLI command to generate report
import asyncio
from production.cli.shared import setup_storage
from production.reporting import ReportingService

async def generate_report_command(evaluation_run_id_str: str):
    """CLI command to generate report from evaluation run ID."""
    # Setup storage
    storage_tuple = await setup_storage(config)
    if not storage_tuple:
        print("Error: Storage not available")
        return

    client, storage_service = storage_tuple

    # Create reporting service
    reporting_service = ReportingService(storage_service)

    # Generate report
    try:
        evaluation_run_id = ObjectId(evaluation_run_id_str)
        report_path = await reporting_service.generate_evaluation_report(evaluation_run_id)
        print(f"✅ Report generated: {report_path}")
    except ValueError as e:
        print(f"❌ Error: {e}")
    except RuntimeError as e:
        print(f"❌ Report generation failed: {e}")
    finally:
        await client.close()

# Run command
asyncio.run(generate_report_command("507f1f77bcf86cd799439011"))
```

---

## Data Models

### EvaluationRunData

Summary data for an evaluation run (suite of tests).

```python
@dataclass
class EvaluationRunData:
    evaluation_run_id: str
    started_at: datetime
    finished_at: datetime
    git_commit: str
    git_branch: str
    environment: str
    target_system: str
    score: float  # 0-100
    num_tests: int
    num_passed: int
    num_failed: int
    aggregated_metrics: dict[str, float]
    system_info_hash: str
    experiment_tags: list[str]
```

### TestReportData

Detailed data for a single test.

```python
@dataclass
class TestReportData:
    test_id: str
    test_name: str
    test_run_id: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    score: float  # 0-100
    score_method: str
    passed: str
    metrics: dict[str, MetricData]
    turns: list[Turn]  # Complete conversation history
```

---

## Report Contents

### Generated PDF Includes:

1. **Evaluation Run Summary**
   - Run metadata (ID, timestamps, duration)
   - Git information (branch, commit)
   - Environment and target system
   - Overall score and test counts
   - Aggregated metrics across all tests

2. **Individual Test Sections** (for each test)
   - Test metadata (ID, name, timestamps)
   - Test score and status
   - Metrics results table
   - Conversation details with turn-by-turn breakdown

3. **Turn Details** (for each conversation turn)
   - Expected text vs translated text comparison
   - Language pair (source → target)
   - Turn timing (start/end)

---

## Benefits Over Previous Implementation

### Before (Hybrid Approach)
```python
# Required live objects + database
pdf_generator.generate(
    scenario=scenario,              # From YAML file ❌
    conversation_manager=conv_mgr,  # Live object ❌
    summary=summary,                # From execution ❌
    # ...
)
```

**Problems:**
- ❌ Requires scenario YAML files
- ❌ Can't regenerate historical reports
- ❌ Coupled to execution context

### After (Database-Only)
```python
# Only needs evaluation run ID
reporting_service.generate_evaluation_report(
    evaluation_run_id  # Just the ID! ✅
)
```

**Benefits:**
- ✅ No external file dependencies
- ✅ Generate reports anytime from DB
- ✅ Clean, simple API
- ✅ Historical reports always work

---

## Error Handling

```python
from bson import ObjectId
from production.reporting import ReportingService

async def safe_report_generation(eval_run_id_str: str):
    """Generate report with proper error handling."""
    try:
        # Convert string to ObjectId
        evaluation_run_id = ObjectId(eval_run_id_str)

        # Generate report
        report_path = await reporting_service.generate_evaluation_report(
            evaluation_run_id
        )

        return report_path

    except ValueError as e:
        # Invalid ObjectId or evaluation run not found
        print(f"Invalid evaluation run: {e}")
        return None

    except RuntimeError as e:
        # PDF generation failed
        print(f"Report generation failed: {e}")
        return None
```

---

## Database Requirements

The reporting service requires the following data in MongoDB:

### Required Collections:
- `evaluation_runs` - Evaluation run documents
- `test_runs` - Test run documents with:
  - Metrics data
  - Turn data (with extended fields)

### Required Turn Fields:
```python
{
  "turn_id": str,
  "start_scn_ms": int,
  "end_scn_ms": int,
  "translated_text": str,      # Actual translation
  "expected_text": str,         # Expected translation
  "source_language": str,       # e.g., "en-US"
  "expected_language": str      # e.g., "es-ES"
}
```

---

## Example Report Output

```
Evaluation Run Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evaluation Run ID: 2024-12-12T10-30Z-abc123
Started: 2024-12-12 10:30:00 UTC
Finished: 2024-12-12 10:35:00 UTC
Duration: 300.00s

Git Branch: main
Git Commit: a1b2c3d4e5f6
Environment: production
Target System: voice_live

Overall Results
┌─────────────────┬─────────────┬──────────┐
│ Overall Score   │ 87.5 / 100  │ [PASS]   │
│ Tests Run       │ 10          │          │
│ Tests Passed    │ 9 (90.0%)   │          │
│ Tests Failed    │ 1 (10.0%)   │          │
└─────────────────┴─────────────┴──────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Test: Medical Consultation Translation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Test ID: test_medical_001
Test Run ID: 2024-12-12T10-30-00Z-test_medical_001
Test Score: 95.0 / 100  [SUCCESS]

Conversation Details
────────────────────────────────────────────────────────
Turn turn_1 at 0ms
┌──────────────────┬─────────────────────────────────────┐
│ Expected Text    │ Hello, how are you feeling today?   │
│ Translated Text  │ Hola, ¿cómo se siente hoy?         │
│ Languages        │ en-US → es-ES                       │
└──────────────────┴─────────────────────────────────────┘
```

---

## Next Steps

1. **Integrate with CLI** - Add command to generate reports by evaluation run ID
2. **Batch reporting** - Generate reports for multiple evaluation runs
3. **Report templates** - Support different report formats
4. **Email integration** - Automatically email reports after test runs

---

## Migration Notes

The old `production.metrics.pdf_report_generator` module is now deprecated. Migrate to the new reporting module:

```python
# Old (deprecated)
from production.metrics.pdf_report_generator import PdfReportGenerator
pdf_gen = PdfReportGenerator()
pdf_gen.generate_suite_report(evaluation_data, test_reports)

# New (recommended)
from production.reporting import EvaluationReportPdfGenerator, CalibrationReportPdfGenerator

# Evaluation report
pdf_gen = EvaluationReportPdfGenerator()
pdf_gen.generate(evaluation_data, test_reports)

# Calibration report
pdf_gen_cal = CalibrationReportPdfGenerator()
pdf_gen_cal.generate(evaluation_data, test_reports)
```

---

## Testing

```python
# Run reporting module tests
pytest production/reporting/tests/
```

---

For questions or issues, see the main production documentation.
