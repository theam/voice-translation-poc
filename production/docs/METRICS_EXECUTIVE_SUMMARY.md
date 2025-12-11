# Translation Service Metrics - Executive Summary

## Overview

Our production testing framework evaluates live speech translation quality through **9 automated metrics** across three key dimensions: accuracy, translation quality, and conversational performance.

---

## Metric Categories

### 1. Accuracy Metrics

**Word Error Rate (WER)**
- **What**: Quantifies word-level translation accuracy using industry-standard Levenshtein distance
- **How**: Compares translated text against reference transcripts, counting substitutions, deletions, and insertions
- **Threshold**: ≤30% error rate (industry standard for conversational speech)
- **Benefit**: Objective, reproducible accuracy measurement aligned with ASR/translation industry benchmarks

**Sequence Validation**
- **What**: Verifies conversation flow maintains expected order
- **How**: Validates events occur in defined sequence (e.g., greeting → question → response)
- **Benefit**: Ensures translation timing doesn't disrupt natural conversation flow

---

### 2. Translation Quality Metrics (LLM-Evaluated)

**Technical Terms Preservation** (90% threshold)
- **What**: Validates medical terminology, proper nouns, and specialized vocabulary
- **Benefit**: Critical for healthcare context - ensures "hypertension" isn't translated as "high blood pressure"

**Information Completeness** (85% threshold)
- **What**: Confirms no information loss or unwanted additions
- **Benefit**: Prevents omissions that could impact patient care (e.g., missing "twice daily" from medication instructions)

**Intent Preservation** (85% threshold)
- **What**: Maintains communicative purpose and tone (question vs. statement, polite vs. direct)
- **Benefit**: Preserves speaker intent - ensures "Could you help?" doesn't become a command "Help me"

**Language Correctness** (100% threshold)
- **What**: Validates language boundaries in bilingual conversations
- **Benefit**: Essential for doctor-patient scenarios where doctor speaks English and patient speaks Spanish - prevents incorrect language switching

---

### 3. Conversational Quality Metrics (80% threshold)

**Intelligibility**
- **What**: Evaluates text clarity and readability (1-5 scale)
- **Benefit**: Identifies garbled or incomprehensible translations that would confuse users

**Segmentation**
- **What**: Assesses sentence boundaries and natural breaks
- **Benefit**: Detects over-fragmentation or run-on sentences that impair understanding

**Context Awareness**
- **What**: Validates responses maintain conversational context using conversation history
- **Benefit**: Catches context loss (e.g., responding about soccer practice when asked about a doctor appointment)

---

## Quality Gates

### Garbled Turn Detection
- **Rule**: Any turn scoring ≤2/5 on intelligibility, segmentation, or context is flagged as "garbled"
- **Threshold**: <10% garbled turn rate per session
- **Benefit**: Single quality gate for overall conversation health

---

## Technology Stack

- **Objective Metrics**: Python-based Levenshtein distance calculation
- **Subjective Metrics**: OpenAI GPT-4o-mini for consistent LLM evaluation
- **Validation**: Calibration system tests metrics against known baselines to detect scoring drift
- **Storage**: MongoDB tracking with git provenance for historical trend analysis
