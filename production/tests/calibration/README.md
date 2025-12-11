# Metrics Calibration System

## Overview

The calibration system validates metric behavior against known expected outcomes. It helps:
- **Validate metric consistency** - Ensure metrics score as expected
- **Detect metric drift** - Track scoring changes over time
- **Tune LLM prompts** - Test prompt modifications quickly
- **Compare LLM models** - Benchmark different models (GPT-4o-mini vs GPT-4o)
- **Set thresholds** - Find optimal pass/fail thresholds

## Architecture

```
Calibration YAML → CalibrationLoader → CalibrationRunner → Metrics → CalibrationReporter
                                                ↓
                                          MongoDB (optional)
```

## YAML Schema

### Basic Structure

```yaml
id: unique_calibration_id
version: "1.0"
description: "What this calibration tests"
metric: intelligibility  # Target metric name
created_at: "2025-12-10"
tags: [calibration, baseline, medical]

# Optional: Override LLM configuration
llm_config:
  model: gpt-4o-mini
  temperature: 0.1

calibration_cases:
  - id: case_id
    description: "What this case tests"
    text: "The text to evaluate"
    metadata:
      source_language: en-US
      target_language: es-ES
      participant_id: patient
      timestamp_ms: 1000
    expected_scores:
      intelligibility_1_5: 5           # Score on 1-5 scale
      intelligibility_normalized: 1.0  # Score on 0-1 scale
    expected_reasoning: "Why we expect this score"
```

### For Context Metric (with conversation history)

```yaml
calibration_cases:
  - id: context_case
    text: "Have you been near anyone sick?"
    conversation_history:  # Prior turns
      - participant_id: patient
        text: "I have a fever and body aches."
        timestamp_ms: 1000
        source_language: en-US
        target_language: es-ES
    metadata:
      source_language: es-ES
      target_language: en-US
      participant_id: nurse
      timestamp_ms: 2000
    expected_scores:
      context_1_5: 5
      context_normalized: 1.0
    expected_reasoning: "Relevant follow-up question"
```

### For WER/Completeness (with ground truth)

```yaml
calibration_cases:
  - id: wer_case
    text: "I have chest pain"           # Recognized text
    expected_text: "I have chest pain"  # Ground truth
    metadata:
      source_language: en-US
      target_language: es-ES
      participant_id: patient
      timestamp_ms: 1000
    expected_scores:
      wer: 0.0  # Perfect match
```

## Score Scales

### 1-5 Scale (Conversational Quality Metrics)
- **5** - Perfect (100%)
- **4** - Good (75%)
- **3** - Acceptable (50%)
- **2** - Poor (25%) ← Garbled threshold
- **1** - Very Poor (0%)

**Conversion to 0-1 scale:** `(score - 1) / 4`

### 0-1 Scale (Other Metrics)
- **1.0** - Perfect (100%)
- **0.9** - Excellent (90%)
- **0.85** - Good (85%)
- **0.5** - Acceptable (50%)
- **0.0** - Complete failure (0%)

## Metrics Supported

### LLM-Based Metrics (Primary Targets)
1. **intelligibility** - Text clarity and readability (1-5)
2. **segmentation** - Sentence boundaries and punctuation (1-5)
3. **context** - Conversational relevance (1-5)
4. **technical_terms** - Technical terminology preservation (0-1)
5. **completeness** - Information completeness (0-1)
6. **intent_preservation** - Communicative intent (0-1)
7. **language_correctness** - Language boundary preservation (0-1)

### Deterministic Metrics
8. **wer** - Word Error Rate (0-1)
9. **sequence** - Event ordering validation

## File Organization

```
production/tests/calibration/
├── README.md                          # This file
├── intelligibility_samples.yaml       # Clarity tests (10 cases)
├── segmentation_samples.yaml          # Punctuation tests (11 cases)
├── context_samples.yaml               # Context awareness tests (10 cases)
├── technical_terms_samples.yaml       # Technical term tests (TODO)
├── completeness_samples.yaml          # Information completeness tests (TODO)
├── intent_preservation_samples.yaml   # Intent tests (TODO)
└── wer_samples.yaml                   # WER tests (TODO)
```

## Usage

### Loading Calibration Files

```python
from production.calibration import CalibrationLoader

loader = CalibrationLoader()

# Load single file
config = loader.load_file("production/tests/calibration/intelligibility_samples.yaml")
print(f"Loaded {len(config.calibration_cases)} cases for {config.metric}")

# Load entire directory
configs = loader.load_directory("production/tests/calibration")
print(f"Loaded {len(configs)} calibration configs")
```

### Running Calibration (CLI - Coming in Phase 2)

```bash
# Run all calibrations
poetry run python -m production.cli calibrate

# Run specific file
poetry run python -m production.cli calibrate \
    --file production/tests/calibration/intelligibility_samples.yaml

# Run only intelligibility calibrations
poetry run python -m production.cli calibrate --metric intelligibility

# Custom tolerance (default: 0.5 on 1-5 scale)
poetry run python -m production.cli calibrate --tolerance 0.3

# Generate report
poetry run python -m production.cli calibrate \
    --output reports/calibration_2025-12-10.md

# Store results in MongoDB
poetry run python -m production.cli calibrate --store
```

## Tolerance Levels

**Tolerance** = Maximum acceptable difference between expected and actual scores.

### Recommended Tolerances

**1-5 Scale Metrics:**
- **Strict:** 0.3 (±0.3 points)
- **Standard:** 0.5 (±0.5 points) ← Default
- **Lenient:** 0.75 (±0.75 points)

**0-1 Scale Metrics:**
- **Strict:** 0.05 (±5%)
- **Standard:** 0.10 (±10%) ← Default
- **Lenient:** 0.15 (±15%)

### Example

```yaml
expected_scores:
  intelligibility_1_5: 4
```

With tolerance 0.5:
- ✅ **Pass:** Actual score 3.5 - 4.5 (within ±0.5)
- ❌ **Fail:** Actual score < 3.5 or > 4.5 (outside tolerance)

## Creating New Calibration Files

### 1. Define Purpose

What are you testing?
- Specific metric behavior
- Edge cases
- Known failure modes
- Model comparison

### 2. Create Test Cases

Include variety:
- **Perfect cases** (score 5) - Baseline expectations
- **Good cases** (score 4) - Minor issues
- **Acceptable cases** (score 3) - Noticeable problems
- **Poor cases** (score 2) - Should flag as garbled
- **Very poor cases** (score 1) - Complete failure
- **Edge cases** - Single words, empty, special characters

### 3. Document Expected Reasoning

Always include `expected_reasoning` to explain:
- Why you expect this score
- What specific issues exist
- What the metric should detect

### 4. Test Across Domains

- Medical terminology
- Casual conversation
- Formal language
- Technical jargon
- Multiple languages

## Calibration Results Interpretation

### High Accuracy (≥90%)
✅ **Good** - Metric is well-calibrated and consistent

**Actions:**
- Use metric with confidence
- Consider tightening tolerance
- Document as baseline

### Medium Accuracy (70-89%)
⚠️ **Fair** - Metric needs tuning

**Actions:**
- Review failed cases
- Adjust LLM prompt
- Consider different model
- Refine scoring rubric

### Low Accuracy (<70%)
❌ **Poor** - Metric needs significant work

**Actions:**
- Redesign LLM prompt
- Test different model (GPT-4o vs GPT-4o-mini)
- Adjust scoring scale
- Review metric logic

## Common Patterns

### Pattern 1: Metric Too Lenient

**Symptom:** Actual scores consistently higher than expected

```
Expected: 2 (poor)    | Actual: 3 (acceptable)
Expected: 2 (poor)    | Actual: 4 (good)
```

**Solution:**
- Strengthen prompt language
- Add specific failure criteria
- Provide clearer examples in prompt

### Pattern 2: Metric Too Strict

**Symptom:** Actual scores consistently lower than expected

```
Expected: 4 (good)    | Actual: 3 (acceptable)
Expected: 5 (perfect) | Actual: 4 (good)
```

**Solution:**
- Soften prompt language
- Reduce failure criteria
- Adjust expectations in calibration

### Pattern 3: Inconsistent Scoring

**Symptom:** High variance in score differences

```
Case A: Expected 3, Actual 3 (diff: 0.0) ✓
Case B: Expected 3, Actual 5 (diff: 2.0) ✗
Case C: Expected 3, Actual 2 (diff: 1.0) ✗
```

**Solution:**
- Increase temperature for more randomness awareness
- Add more detailed scoring criteria
- Test with GPT-4o for better consistency

### Pattern 4: Model Drift Over Time

**Symptom:** Calibration accuracy decreases in later runs

**Solution:**
- Re-run calibrations regularly
- Store results in MongoDB for tracking
- Alert on significant drift
- Update prompts as needed

## Best Practices

### 1. Start Small
Begin with 5-10 cases per metric, then expand

### 2. Cover Edge Cases
- Very short text ("Yes")
- Very long text (run-on sentences)
- Missing punctuation
- Garbled text
- Perfect examples

### 3. Use Real Examples
Base calibration cases on actual translation failures

### 4. Document Reasoning
Always explain why you expect a certain score

### 5. Test Regularly
Run calibrations after:
- Prompt changes
- Model updates
- Threshold adjustments
- Major code changes

### 6. Track Over Time
Store results in MongoDB to detect drift

### 7. Compare Models
Test GPT-4o-mini vs GPT-4o to find best cost/quality balance

## Future Enhancements

### Phase 2 (In Progress)
- [ ] CalibrationRunner implementation
- [ ] CalibrationReporter (console output)
- [ ] CLI command integration

### Phase 3 (Planned)
- [ ] MongoDB storage
- [ ] Drift detection (compare runs over time)
- [ ] Report generation (markdown/JSON)
- [ ] Automated alerts on failures

### Phase 4 (Future)
- [ ] Web dashboard for results
- [ ] Continuous calibration in CI/CD
- [ ] A/B testing for prompt variations
- [ ] Cost tracking per model/run

## Contributing

### Adding New Calibration Cases

1. Choose target metric
2. Create test case with clear expected score
3. Document expected reasoning
4. Run calibration to validate
5. Adjust if needed

### Adding New Calibration Files

1. Copy existing template
2. Update id, description, metric
3. Create 5-10 diverse cases
4. Test with CLI (once available)
5. Document any special considerations

## Troubleshooting

### "Missing required fields" Error

**Cause:** YAML file missing required fields

**Solution:** Ensure your YAML has:
```yaml
id: ...
version: ...
description: ...
metric: ...
created_at: ...
```

### "No YAML files found" Warning

**Cause:** Directory is empty or files have wrong extension

**Solution:**
- Use `.yaml` or `.yml` extension
- Place files in `production/tests/calibration/`

### Calibration Failing Unexpectedly

**Cause:** LLM scoring differently than expected

**Solution:**
1. Review actual_reasoning in results
2. Adjust expected_score if LLM reasoning is valid
3. Refine prompt if LLM is wrong
4. Check LLM model (temperature, model version)

---

## Summary

The calibration system provides a systematic way to validate and improve metrics by:
- Testing against known expected outcomes
- Detecting metric drift over time
- Enabling rapid prompt iteration
- Comparing different LLM models

**Current Status:** Phase 1 Complete ✅
- Data models ✅
- YAML loader ✅
- Sample files (3 metrics) ✅

**Next:** Phase 2 - Runner, Reporter, CLI integration
