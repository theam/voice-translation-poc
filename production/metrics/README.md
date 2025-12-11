# Production Metrics

Metrics for evaluating translation scenario outcomes in the production framework.

## Overview

The production framework uses class-based metrics that implement the `Metric` Protocol. Each metric receives full scenario context (`Expectations` + `CollectedEvent[]`) and returns a `MetricResult` with pass/fail status, value, and detailed analysis.

## Available Metrics

### 1. SequenceMetric

**Purpose**: Validates that events occur in the expected order.

**Use Case**: Ensure conversation flow is maintained (greetings before questions, etc.).

**Configuration** (YAML):
```yaml
expectations:
  sequence:
    - agent_greeting
    - patient_response
    - agent_question
```

**Output**:
- `passed`: True if events occurred in specified order
- `value`: 1.0 if passed, 0.0 if failed
- `details`: Expected vs actual sequence

**Example Result**:
```json
{
  "metric_name": "sequence",
  "passed": true,
  "value": 1.0,
  "details": {
    "expected_sequence": ["agent_greeting", "patient_response"],
    "actual_sequence": ["agent_greeting", "patient_response"],
    "matched": true
  }
}
```

---

### 2. WERMetric (Word Error Rate)

**Purpose**: Calculates Word Error Rate for translation/ASR accuracy using Levenshtein distance.

**Use Case**: Quantitative accuracy measurement - standard metric for ASR/translation systems.

**Formula**: `WER = (S + D + I) / N`
- S = Substitutions (words replaced)
- D = Deletions (words removed)
- I = Insertions (words added)
- N = Number of words in reference

**Configuration** (YAML):
```yaml
expectations:
  transcripts:
    - id: translation_accuracy
      event_id: agent_greeting
      source_language: en-US
      target_language: es-ES
      expected_text: "Hola, ¿cómo estás hoy?"  # Reference text for WER calculation
```

**Features**:
- ✅ Text normalization (contraction expansion, lowercase, punctuation removal)
- ✅ Detailed edit operation breakdown (S/D/I counts)
- ✅ Per-expectation and overall WER calculation
- ✅ Configurable threshold (default: 0.3 = 30%)
- ✅ Human-readable interpretation

**Output**:
- `passed`: True if WER <= threshold
- `value`: Overall WER (0.0 = perfect, 1.0+ = very poor)
- `details`: Edit operations, per-expectation results, interpretation

**Example Result**:
```json
{
  "metric_name": "wer",
  "passed": true,
  "value": 0.25,
  "reason": null,
  "details": {
    "overall_wer": "25.00%",
    "threshold": 0.3,
    "interpretation": "Acceptable (15-30% error)",
    "total_errors": 1,
    "total_reference_words": 4,
    "wer_results": [
      {
        "id": "translation_accuracy",
        "status": "passed",
        "wer": 0.25,
        "wer_percentage": "25.00%",
        "substitutions": 1,
        "deletions": 0,
        "insertions": 0,
        "total_errors": 1,
        "reference_words": 4,
        "hypothesis_words": 4,
        "reference_text": "Hola, ¿cómo estás hoy?",
        "hypothesis_text": "Hola cómo está hoy",
        "interpretation": "Acceptable (15-30% error)"
      }
    ]
  }
}
```

**WER Interpretation Guide**:
- 0.00: Perfect recognition
- ≤ 0.05: Excellent (< 5% error)
- ≤ 0.15: Good (5-15% error)
- ≤ 0.30: Acceptable (15-30% error) ← Default threshold
- ≤ 0.50: Poor (30-50% error)
- > 0.50: Very poor (> 50% error)

**Advanced Usage**:
```python
# Custom threshold and language
WERMetric(expectations, events, threshold=0.2, language="es")
```

**Example Calculation**:
```
Reference:  "I have chest pain"          → [i, have, chest, pain]
Hypothesis: "I had chest pains"          → [i, had, chest, pains]

Normalized reference:  [i, have, chest, pain]   (4 words)
Normalized hypothesis: [i, had, chest, pains]   (4 words)

Edit operations:
  - "have" → "had" (substitution)
  - "pain" → "pains" (substitution)
  Total: 2 substitutions

WER = 2/4 = 0.50 (50%)  ✗ FAIL (exceeds 30% threshold)
```

---

### 3. TechnicalTermsMetric

**Purpose**: Evaluates accuracy of technical terms, proper nouns, acronyms, and specialized vocabulary using LLM evaluation.

**Use Case**: Ensures critical terminology (medical terms, proper names, technical jargon) is correctly preserved in translations.

**Configuration** (YAML):
```yaml
expectations:
  transcripts:
    - id: medical_terminology
      event_id: patient_symptoms
      source_language: en-US
      target_language: es-ES
      expected_text: "Patient has hypertension and takes lisinopril daily"
```

**Features**:
- ✅ LLM-powered evaluation (OpenAI GPT-4o-mini)
- ✅ Identifies technical terms automatically
- ✅ Evaluates preservation/translation accuracy
- ✅ Provides detailed reasoning for scores
- ✅ Higher threshold (90% vs WER's 30%)
- ✅ Handles cases with no technical content

**Output**:
- `passed`: True if technical terms score >= 90%
- `value`: Overall technical terms accuracy (0.0-1.0)
- `details`: Per-expectation results, terms found, correct/incorrect terms

**Example Result**:
```json
{
  "metric_name": "technical_terms",
  "passed": true,
  "value": 0.95,
  "reason": null,
  "details": {
    "overall_score": "95.00%",
    "threshold": 0.90,
    "evaluations": 1,
    "results": [
      {
        "id": "medical_terminology",
        "status": "evaluated",
        "score": 0.95,
        "passed": true,
        "reasoning": "Technical terms 'hypertension' and 'lisinopril' correctly preserved. Minor variation in 'daily' translation acceptable.",
        "technical_terms_found": ["hypertension", "lisinopril", "daily"],
        "correct_terms": ["hypertension", "lisinopril"],
        "incorrect_terms": [],
        "has_technical_content": true,
        "reference_text": "Patient has hypertension and takes lisinopril daily",
        "hypothesis_text": "Paciente tiene hipertensión y toma lisinopril diariamente",
        "tokens_used": 245,
        "model": "gpt-4o-mini"
      }
    ]
  }
}
```

**LLM Scoring Guide**:
- 1.0: All technical terms perfect
- 0.9-0.95: Excellent - minor variation in non-critical term
- 0.8-0.85: Good - one term slightly incorrect but understandable
- 0.7-0.75: Acceptable - some terms wrong but meaning preserved
- 0.5-0.65: Poor - multiple critical terms incorrect
- <0.5: Very poor - major terminology errors

**Special Case**: If no technical terms are detected, the metric returns a score of 1.0 with `has_technical_content: false`.

**Advanced Usage**:
```python
# Custom threshold
TechnicalTermsMetric(expectations, events, threshold=0.95)
```

**Configuration Requirements**:
- Environment variable: `AZURE_AI_FOUNDRY_KEY` (OpenAI API key)
- Environment variable: `OPENAI_BASE_URL` (Azure OpenAI endpoint)
- Dependencies: `openai` library (automatically installed)

**Example Evaluation**:
```
Reference:  "Patient has hypertension and takes lisinopril"
Hypothesis: "Patient has high blood pressure and takes lisinopril"

LLM Analysis:
  - Technical terms found: ["hypertension", "lisinopril"]
  - Correct: ["lisinopril"]
  - Incorrect: [{"expected": "hypertension", "recognized": "high blood pressure"}]
  - Score: 0.50 (50%) ✗ FAIL (below 90% threshold)
  - Reasoning: "Critical medical term 'hypertension' was mistranslated to layman's term 'high blood pressure'. While semantically similar, medical terminology should be preserved."
```

---

### 4. CompletenessMetric

**Purpose**: Evaluates information completeness - ensures all information from the expected text is preserved in the translation without omissions or additions.

**Use Case**: Verifies that translations maintain information integrity, critical for scenarios where complete information transfer is essential (medical, legal, technical domains).

**Configuration** (YAML):
```yaml
expectations:
  transcripts:
    - id: information_completeness
      event_id: patient_history
      source_language: en-US
      target_language: es-ES
      expected_text: "Patient has diabetes, hypertension, and takes metformin twice daily"
```

**Features**:
- ✅ LLM-powered evaluation (OpenAI GPT-4o-mini)
- ✅ Identifies omissions (missing information)
- ✅ Identifies additions (extra information not in original)
- ✅ Detailed reasoning for scores
- ✅ Threshold: 85% completeness required
- ✅ Critical for ensuring no information loss

**Output**:
- `passed`: True if completeness score >= 85%
- `value`: Overall completeness score (0.0-1.0)
- `details`: Per-expectation results, omissions list, additions list, reasoning

**Example Result**:
```json
{
  "metric_name": "completeness",
  "passed": false,
  "value": 0.70,
  "reason": "Completeness score 70.00% below threshold 85%",
  "details": {
    "overall_score": "70.00%",
    "threshold": 0.85,
    "evaluations": 1,
    "results": [
      {
        "id": "information_completeness",
        "status": "evaluated",
        "score": 0.70,
        "passed": false,
        "reasoning": "Translation missing critical medical information. 'Hypertension' and medication frequency 'twice daily' were omitted, which are essential details for patient care.",
        "omissions": ["hypertension", "twice daily"],
        "additions": [],
        "reference_text": "Patient has diabetes, hypertension, and takes metformin twice daily",
        "hypothesis_text": "Patient has diabetes and takes metformin",
        "tokens_used": 278,
        "model": "gpt-4o-mini"
      }
    ]
  }
}
```

**LLM Scoring Guide**:
- 1.0: Perfect - all information preserved, nothing missing or added
- 0.9-0.95: Excellent - minor detail missing or slight rephrasing
- 0.8-0.85: Good - one small element missing or added
- 0.7-0.75: Acceptable - some information missing but core preserved
- 0.5-0.65: Poor - significant omissions or additions
- <0.5: Very poor - major information loss or distortion

**Advanced Usage**:
```python
# Custom threshold (require 90% completeness)
CompletenessMetric(expectations, events, threshold=0.90)
```

**Configuration Requirements**:
- Environment variable: `AZURE_AI_FOUNDRY_KEY` (OpenAI API key)
- Environment variable: `OPENAI_BASE_URL` (Azure OpenAI endpoint)
- Dependencies: `openai` library (automatically installed)

**Example Evaluation**:
```
Reference:  "Patient has three symptoms: fever, cough, and fatigue"
Hypothesis: "Patient has fever and cough"

LLM Analysis:
  - Omissions: ["fatigue", "three symptoms"]
  - Additions: []
  - Score: 0.75 (75%) ✗ FAIL (below 85% threshold)
  - Reasoning: "Translation omits 'fatigue' symptom and the quantifier 'three'. While two symptoms are preserved, the omission of the third symptom and quantifier reduces information completeness."
```

**Key Differences from WER**:
- **WER**: Measures word-level accuracy (exact match, substitutions)
- **Completeness**: Measures information preservation (semantic content)
- Example: "I have chest pain" vs "I have pain in my chest"
  - WER: High error rate (different word order)
  - Completeness: Perfect score (same information)

---

### 5. IntentPreservationMetric

**Purpose**: Evaluates whether the speaker's communicative intent, purpose, and pragmatic goals are preserved in the translation.

**Use Case**: Ensures that the speaker's intended message, tone, and communicative function (question, request, command) remain intact in translation.

**Configuration** (YAML):
```yaml
expectations:
  transcripts:
    - id: intent_check
      event_id: patient_request
      source_language: en-US
      target_language: es-ES
      expected_text: "Could you please help me with this?"
```

**Features**:
- ✅ LLM-powered evaluation (OpenAI GPT-4o-mini)
- ✅ Identifies communicative intent type (question, statement, request, command, greeting)
- ✅ Evaluates tone preservation
- ✅ Detects pragmatic issues (politeness, formality changes)
- ✅ Threshold: 85% intent preservation required
- ✅ Critical for maintaining speaker's communicative goals

**Output**:
- `passed`: True if intent preservation score >= 85%
- `value`: Overall intent preservation score (0.0-1.0)
- `details`: Per-expectation results, intent types, tone match, pragmatic issues

**Example Result**:
```json
{
  "metric_name": "intent_preservation",
  "passed": false,
  "value": 0.70,
  "reason": "Intent preservation score 70.00% below threshold 85%",
  "details": {
    "overall_score": "70.00%",
    "threshold": 0.85,
    "evaluations": 1,
    "results": [
      {
        "id": "intent_check",
        "status": "evaluated",
        "score": 0.70,
        "passed": false,
        "reasoning": "Intent changed from polite request to direct command. Loss of politeness markers ('could you please') significantly alters the pragmatic function and tone.",
        "expected_intent": "Polite request for assistance with emphasis on courtesy",
        "recognized_intent": "Direct command to provide help",
        "intent_type": "request",
        "tone_match": false,
        "pragmatic_issues": ["Loss of politeness", "Changed from indirect to direct speech"],
        "reference_text": "Could you please help me with this?",
        "hypothesis_text": "Help me with this",
        "tokens_used": 312,
        "model": "gpt-4o-mini"
      }
    ]
  }
}
```

**LLM Scoring Guide**:
- 1.0: Perfect - intent completely preserved, listener would understand identically
- 0.9-0.95: Excellent - intent clear, minor tonal difference
- 0.8-0.85: Good - main intent preserved, some nuance lost
- 0.7-0.75: Acceptable - core intent recognizable but weakened
- 0.5-0.65: Poor - intent partially lost or ambiguous
- <0.5: Very poor - intent significantly altered or lost

**Intent Types**:
- **Question**: Seeking information ("What time is it?")
- **Statement**: Providing information ("I have a headache")
- **Request**: Asking for action ("Could you help?")
- **Command**: Directing action ("Close the door")
- **Greeting**: Social interaction ("Good morning")
- **Other**: Complex or mixed intents

**Advanced Usage**:
```python
# Custom threshold (require 90% intent preservation)
IntentPreservationMetric(expectations, events, threshold=0.90)
```

**Configuration Requirements**:
- Environment variable: `AZURE_AI_FOUNDRY_KEY` (OpenAI API key)
- Environment variable: `OPENAI_BASE_URL` (Azure OpenAI endpoint)
- Dependencies: `openai` library (automatically installed)

**Example Evaluations**:

**Example 1: Politeness Loss**
```
Reference:  "Could you please help me?"
Hypothesis: "Help me"

LLM Analysis:
  - Expected intent: "Polite request for assistance"
  - Recognized intent: "Direct command for help"
  - Intent type: request
  - Tone match: false
  - Pragmatic issues: ["Loss of politeness markers", "Changed formality level"]
  - Score: 0.70 (70%) ✗ FAIL (below 85% threshold)
```

**Example 2: Intent Preserved**
```
Reference:  "I'm feeling tired"
Hypothesis: "I am feeling tired"

LLM Analysis:
  - Expected intent: "Statement of current physical state"
  - Recognized intent: "Statement of current physical state"
  - Intent type: statement
  - Tone match: true
  - Pragmatic issues: []
  - Score: 1.0 (100%) ✓ PASS
```

**Example 3: Question vs Statement**
```
Reference:  "What time is it?"
Hypothesis: "It is time"

LLM Analysis:
  - Expected intent: "Question seeking time information"
  - Recognized intent: "Vague statement about time"
  - Intent type: question
  - Tone match: false
  - Pragmatic issues: ["Question converted to statement", "Lost information-seeking function"]
  - Score: 0.30 (30%) ✗ FAIL (intent fundamentally altered)
```

**Key Differences from Other Metrics**:
- **WER**: Word-level accuracy (ignores meaning)
- **Completeness**: Information preservation (what is said)
- **Intent Preservation**: Communicative function (why it is said)
- **Technical Terms**: Terminology accuracy

Example: "Could you help?" vs "Help me"
- WER: 50% (2/4 words different)
- Completeness: 90% (same information requested)
- Intent Preservation: 70% (politeness lost, request → command)

---

### 6. LanguageCorrectnessMetric

**Purpose**: Verifies that each sentence in the recognized text matches the LANGUAGE of the corresponding sentence in the expected text in bilingual/multilingual conversations.

**Use Case**: Critical for bilingual conversations where language switching is expected and must be preserved. Ensures that if a speaker says something in English, it's recognized in English, and if they say something in Spanish, it's recognized in Spanish.

**IMPORTANT**: This metric ONLY checks language matching, NOT translation quality, semantic accuracy, or completeness.

**Configuration** (YAML):
```yaml
expectations:
  transcripts:
    - id: bilingual_conversation
      event_id: conversation_turn
      source_language: en-US
      target_language: es-ES
      expected_text: "Hello, how are you? Estoy bien, gracias."
```

**Features**:
- ✅ LLM-powered evaluation (OpenAI GPT-4o-mini)
- ✅ Sentence-level language detection and matching
- ✅ Intelligent sentence pairing (handles omissions)
- ✅ Supports bilingual/multilingual conversations
- ✅ Threshold: 100% (all matched sentences must have matching languages)
- ✅ Critical for preserving language boundaries

**Output**:
- `passed`: True if ALL matched sentences have matching languages (score = 1.0)
- `value`: Proportion of matched sentences with correct language (0.0-1.0)
- `details`: Sentence pairs, language detection, missing sentences, issues

**Example Result**:
```json
{
  "metric_name": "language_correctness",
  "passed": false,
  "value": 0.50,
  "reason": "Language correctness score 50.00% below threshold 100%",
  "details": {
    "overall_score": "50.00%",
    "threshold": 1.0,
    "evaluations": 1,
    "results": [
      {
        "id": "bilingual_conversation",
        "status": "evaluated",
        "score": 0.50,
        "passed": false,
        "reasoning": "Split into 2 sentences. Sentence 1 (English) matches correctly. Sentence 2 expected Spanish 'Estoy bien, gracias' but recognized English 'I am fine, thank you'. Language mismatch.",
        "sentence_pairs": [
          {
            "expected_sentence": "Hello, how are you?",
            "recognized_sentence": "Hello, how are you?",
            "expected_language": "en",
            "recognized_language": "en",
            "is_correctly_translated": true,
            "issue": ""
          },
          {
            "expected_sentence": "Estoy bien, gracias.",
            "recognized_sentence": "I am fine, thank you.",
            "expected_language": "es",
            "recognized_language": "en",
            "is_correctly_translated": false,
            "issue": "Expected Spanish but got English"
          }
        ],
        "correct_count": 1,
        "total_count": 2,
        "missing_count": 0,
        "missing_sentences": [],
        "issues": [
          {
            "expected": "Estoy bien, gracias.",
            "recognized": "I am fine, thank you.",
            "expected_lang": "es",
            "recognized_lang": "en",
            "issue": "Expected Spanish but got English"
          }
        ],
        "reference_text": "Hello, how are you? Estoy bien, gracias.",
        "hypothesis_text": "Hello, how are you? I am fine, thank you.",
        "tokens_used": 425,
        "model": "gpt-4o-mini"
      }
    ]
  }
}
```

**Scoring**:
- **100% threshold**: ALL matched sentences must have matching languages
- Missing sentences are excluded from scoring (not counted as failures)
- Only evaluates language match, not semantic content

**Advanced Usage**:
```python
# Standard usage (100% threshold)
LanguageCorrectnessMetric(expectations, events)

# Custom threshold (e.g., 90% - allow some language mixing)
LanguageCorrectnessMetric(expectations, events, threshold=0.90)
```

**Configuration Requirements**:
- Environment variable: `AZURE_AI_FOUNDRY_KEY` (OpenAI API key)
- Environment variable: `OPENAI_BASE_URL` (Azure OpenAI endpoint)
- Dependencies: `openai` library (automatically installed)

**Example Evaluations**:

**Example 1: Perfect Match (PASS)**
```
Expected:  "Hello, how are you? Estoy bien."
Recognized: "Hello, how are you? Estoy bien."

LLM Analysis:
  - Sentence 1: "Hello, how are you?" (en) → "Hello, how are you?" (en) ✓
  - Sentence 2: "Estoy bien." (es) → "Estoy bien." (es) ✓
  - Score: 1.0 (100%) ✓ PASS
```

**Example 2: Language Mismatch (FAIL)**
```
Expected:  "Hello, how are you? Estoy bien."
Recognized: "Hello, how are you? I'm fine."

LLM Analysis:
  - Sentence 1: "Hello, how are you?" (en) → "Hello, how are you?" (en) ✓
  - Sentence 2: "Estoy bien." (es) → "I'm fine." (en) ✗
  - Score: 0.50 (50%) ✗ FAIL (below 100% threshold)
  - Issue: Expected Spanish but got English
```

**Example 3: Semantic Incorrect but Language Correct (PASS)**
```
Expected:  "I have a fever. Tengo escalofríos."
Recognized: "I have a headache. Tengo náuseas."

LLM Analysis:
  - Sentence 1: "I have a fever." (en) → "I have a headache." (en) ✓
  - Sentence 2: "Tengo escalofríos." (es) → "Tengo náuseas." (es) ✓
  - Score: 1.0 (100%) ✓ PASS
  - Note: Semantic content is wrong, but languages match correctly
```

**Example 4: Missing Sentences (Partial)**
```
Expected:  "I have a fever. Está bien. My son had the flu."
Recognized: "I have a fever. My son had the flu."

LLM Analysis:
  - Sentence 1: "I have a fever." (en) → "I have a fever." (en) ✓
  - Sentence 2: "Está bien." (es) → MISSING (skipped in scoring)
  - Sentence 3: "My son had the flu." (en) → "My son had the flu." (en) ✓
  - Score: 1.0 (100%) ✓ PASS (2/2 matched sentences correct)
  - Missing count: 1
```

**Key Characteristics**:
- **Language-only focus**: Does NOT evaluate translation quality, semantic accuracy, or completeness
- **Sentence-level**: Evaluates each sentence independently
- **Intelligent matching**: Uses semantic similarity to match sentences even when wording differs or sentences are missing
- **Bilingual support**: Designed for conversations where speakers switch languages
- **Strict threshold**: Requires 100% language matching by default

**Use Cases**:
1. **Bilingual medical conversations**: Doctor (English) ↔ Patient (Spanish)
2. **Customer service**: Agent (English) ↔ Customer (native language)
3. **Multilingual meetings**: Participants speaking different languages
4. **Translation quality control**: Verify language boundaries are preserved

**What This Metric Does NOT Check**:
- ❌ Translation accuracy or semantic correctness
- ❌ Information completeness or omissions
- ❌ Technical terminology preservation
- ❌ Communicative intent or tone

**Complementary Metrics**:
Use alongside other metrics for complete evaluation:
- **WER**: Word-level accuracy
- **Completeness**: Information preservation
- **Technical Terms**: Terminology accuracy
- **Intent Preservation**: Communicative goals
- **Language Correctness**: Language boundary preservation

---

## Metric Interface

### Base Protocol

All metrics implement the `Metric` Protocol:

```python
class Metric(Protocol):
    name: str  # Unique metric identifier

    def run(self) -> MetricResult:
        """Execute metric calculation and return result."""
        ...
```

### MetricResult

```python
@dataclass
class MetricResult:
    metric_name: str          # Name of the metric
    passed: bool              # Whether metric passed threshold
    value: float | None       # Numeric result (optional)
    reason: str | None        # Explanation for failure (optional)
    details: Dict[str, Any] | None  # Additional details (optional)
```

---

## Adding New Metrics

### 1. Create Metric Class

Create `production/metrics/my_metric.py`:

```python
from production.capture.collector import CollectedEvent
from production.scenario_engine.models import Expectations
from .base import Metric, MetricResult

class MyMetric(Metric):
    """Description of what this metric evaluates."""

    name = "my_metric"

    def __init__(self, expectations: Expectations, events: Sequence[CollectedEvent]):
        self.expectations = expectations
        self.events = events

    def run(self) -> MetricResult:
        # Extract data from events
        transcript_events = [e for e in self.events if e.event_type == "translated_text"]

        # Calculate metric
        value = self._calculate(transcript_events)
        passed = value >= threshold

        return MetricResult(
            metric_name=self.name,
            passed=passed,
            value=value,
            reason="Explanation if failed",
            details={"extra": "information"}
        )
```

### 2. Register in Factory

Update `production/metrics/__init__.py`:

```python
from .my_metric import MyMetric

def get_metrics(expectations: Expectations, events: Sequence[CollectedEvent]) -> List[Metric]:
    return [
        TranscriptContainsMetric(expectations, events),
        SequenceMetric(expectations, events),
        WERMetric(expectations, events),
        MyMetric(expectations, events),  # Add here
    ]
```

### 3. Test

Create test scenario in `production/tests/scenarios/`:

```yaml
id: test_my_metric
# ... scenario definition ...
expectations:
  # Add expectations your metric needs
```

---

## Testing Metrics

### Unit Testing

```python
def test_wer_metric():
    # Create test expectations
    expectations = Expectations(
        transcripts=[
            TranscriptExpectation(
                id="test",
                event_id="event1",
                source_language="en-US",
                target_language="es-ES",
                expected_text="hola mundo"
            )
        ]
    )

    # Create test events
    events = [
        CollectedEvent(
            event_type="translated_text",
            timestamp_ms=1000,
            text="hola mundo",
            source_language="en-US",
            target_language="es-ES",
            raw={"event_id": "event1"}
        )
    ]

    # Run metric
    metric = WERMetric(expectations, events)
    result = metric.run()

    # Assert
    assert result.passed
    assert result.value == 0.0  # Perfect match
```

### Integration Testing

```bash
# Run scenario with metrics
poetry run python -m production.cli run-test \
    production/tests/scenarios/wer_example_en_to_es.yaml
```

---

## Dependencies

### Core Dependencies
- `production.capture.collector.CollectedEvent` - Event data from scenario execution
- `production.scenario_engine.models.Expectations` - Scenario expectations

### WER Metric Dependencies
- `production.utils.text_normalization` - Text preprocessing utilities
  - Contraction expansion (I'm → I am)
  - Punctuation removal
  - Lowercase normalization
  - Whitespace normalization

### Installing Dependencies

All dependencies are included in the production framework:

```bash
# Already available, no additional installation needed
poetry install
```

---

## Best Practices

### 1. Use Multiple Metrics

Combine metrics for comprehensive evaluation:

```yaml
expectations:
  # WER accuracy measurement
  transcripts:
    - id: translation_check
      expected_text: "I have chest pain"  # Reference for WER
      regex: "chest.*pain"  # Optional regex for pattern matching

  # Ordering validation
  sequence:
    - greeting
    - symptoms
    - diagnosis

  # Timing validation
  max_latency_ms: 3000
```

### 2. Set Appropriate Thresholds

- **WER < 0.10**: High-stakes medical/legal contexts
- **WER < 0.30**: General conversation (default)
- **WER < 0.50**: Casual communication, noisy environments

### 3. Normalize Reference Text

For WER, provide clean reference text in `expected_text`:

```yaml
# Good - clean reference text
expected_text: "I have chest pain"

# Avoid - noisy formatting (though normalization will handle it)
expected_text: "I  have... chest pain!"  # Extra spaces, punctuation
```

### 4. Test Edge Cases

- Empty translations
- Very short utterances (1-2 words)
- Mixed languages
- Special characters

---

## Troubleshooting

### WER Always 1.0

**Cause**: No matching events found for expectations

**Solution**: Check `event_id`, `source_language`, and `target_language` in expectations match collected events

### WER Unexpectedly High

**Cause**: Text normalization differences

**Solution**: Verify both texts normalize the same way:
```python
from production.utils.text_normalization import normalize_text_for_wer
print(normalize_text_for_wer("I'm fine!"))  # → "i am fine"
```

### Metrics Not Running

**Cause**: Metric not registered in factory

**Solution**: Add metric to `get_metrics()` in `__init__.py`

---

## References

- [Word Error Rate (Wikipedia)](https://en.wikipedia.org/wiki/Word_error_rate)
- [Levenshtein Distance](https://en.wikipedia.org/wiki/Levenshtein_distance)
- [Production Framework Architecture](../REFACTORING.md)
- [Metrics Migration Guide](../METRICS_MIGRATION.md)
