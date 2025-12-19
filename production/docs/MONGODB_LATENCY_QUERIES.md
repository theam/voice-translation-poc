# MongoDB Latency Debugging Queries

This document contains MongoDB queries used to investigate and debug latency metrics in the production testing framework.

## Quick Reference

```bash
# Connect to MongoDB container
docker exec vt-mongodb mongosh vt_metrics --quiet

# Or use the Make target
make mongo
```

---

## 1. Find Negative Latencies

### Check for Negative Latency Values

Identifies turns with negative latency (indicates timing calculation issues):

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$project: {
    test_id: 1,
    turn_id: "$turns.turn_id",
    latency_ms: "$turns.latency.latency_ms"
  }},
  {$match: {latency_ms: {$ne: null}}},
  {$sort: {latency_ms: 1}},
  {$limit: 10}
]).forEach(doc => printjson(doc))
```

### Group Negative Latencies by Test

Shows which tests have negative latencies and how many:

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$match: {"turns.latency.latency_ms": {$lt: 0}}},
  {$group: {
    _id: "$test_id",
    count: {$sum: 1},
    min_latency: {$min: "$turns.latency.latency_ms"},
    sample_turn_id: {$first: "$turns.turn_id"},
    sample_eval_id: {$first: "$evaluation_run_id"}
  }},
  {$sort: {count: -1}}
]).forEach(doc => {
  print("Test:", doc._id);
  print("  Negative latency count:", doc.count);
  print("  Min latency (ms):", doc.min_latency);
  print("  Sample turn:", doc.sample_turn_id);
  print("  Sample eval:", doc.sample_eval_id);
  print("");
})
```

---

## 2. Detailed Turn Inspection

### Get Full Latency Breakdown for Specific Turn

Useful for understanding timing issues:

```javascript
db.test_runs.aggregate([
  {$match: {"turns.latency.latency_ms": -21443}},
  {$project: {
    test_id: 1,
    turns: {$filter: {
      input: "$turns",
      as: "turn",
      cond: {$eq: ["$$turn.latency.latency_ms", -21443]}
    }}
  }}
]).forEach(doc => {
  print("Test ID:", doc.test_id);
  printjson(doc.turns[0].latency);
})
```

### Inspect Specific Test Run with Multiple Turns

Check for turn overlap and timing issues:

```javascript
db.test_runs.aggregate([
  {$match: {
    test_id: "headache_appt",
    "turns.turn_id": "doctor_turn_2"
  }},
  {$limit: 1},
  {$project: {
    test_id: 1,
    turns: {$filter: {
      input: "$turns",
      as: "turn",
      cond: {$in: ["$$turn.turn_id", ["patient_turn_1", "doctor_turn_2"]]}
    }}
  }}
]).forEach(doc => {
  doc.turns.forEach(turn => {
    print("\n=== Turn:", turn.turn_id, "===");
    print("Start:", turn.start_ms, "ms");
    print("End:", turn.end_ms, "ms");
    if (turn.latency) {
      print("\nLatency data:");
      print("  first_outbound_ms:", turn.latency.first_outbound_ms);
      print("  last_outbound_ms:", turn.latency.last_outbound_ms);
      print("  first_audio_response_ms:", turn.latency.first_audio_response_ms);
      print("  last_audio_response_ms:", turn.latency.last_audio_response_ms);
      print("  latency_ms:", turn.latency.latency_ms);
      print("  audio_duration_ms:", turn.latency.audio_duration_ms);
    }
  });
})
```

---

## 3. Latency Distribution Analysis

### Overall Statistics

Get min, max, avg, and percentiles:

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$match: {"turns.latency.latency_ms": {$gte: 0}}},
  {$group: {
    _id: null,
    count: {$sum: 1},
    min: {$min: "$turns.latency.latency_ms"},
    max: {$max: "$turns.latency.latency_ms"},
    avg: {$avg: "$turns.latency.latency_ms"},
    latencies: {$push: "$turns.latency.latency_ms"}
  }},
  {$project: {
    count: 1,
    min: 1,
    max: 1,
    avg: 1,
    p50: {$arrayElemAt: [{$sortArray: {input: "$latencies", sortBy: 1}}, {$floor: {$multiply: [0.50, "$count"]}}]},
    p90: {$arrayElemAt: [{$sortArray: {input: "$latencies", sortBy: 1}}, {$floor: {$multiply: [0.90, "$count"]}}]},
    p95: {$arrayElemAt: [{$sortArray: {input: "$latencies", sortBy: 1}}, {$floor: {$multiply: [0.95, "$count"]}}]},
    p99: {$arrayElemAt: [{$sortArray: {input: "$latencies", sortBy: 1}}, {$floor: {$multiply: [0.99, "$count"]}}]}
  }}
]).forEach(doc => {
  print("Total turns with valid latency:", doc.count);
  print("Min:", doc.min, "ms");
  print("Max:", doc.max, "ms");
  print("Avg:", Math.round(doc.avg), "ms");
  print("P50 (median):", doc.p50, "ms");
  print("P90:", doc.p90, "ms");
  print("P95:", doc.p95, "ms");
  print("P99:", doc.p99, "ms");
})
```

### Find High Latency Tests

Identify tests with latency >10 seconds:

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$match: {"turns.latency.latency_ms": {$gt: 10000}}},
  {$group: {
    _id: "$test_id",
    count: {$sum: 1},
    max_latency: {$max: "$turns.latency.latency_ms"},
    avg_latency: {$avg: "$turns.latency.latency_ms"}
  }},
  {$sort: {max_latency: -1}}
]).forEach(doc => {
  print("Test:", doc._id);
  print("  Count:", doc.count, "turns");
  print("  Max:", doc.max_latency, "ms");
  print("  Avg:", Math.round(doc.avg_latency), "ms");
  print("");
})
```

---

## 4. Find Extreme Values

### Find Minimum Latency Turn

Locate the fastest response:

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$match: {"turns.latency.latency_ms": 614}},  // Replace with actual min
  {$limit: 1},
  {$project: {
    test_id: 1,
    evaluation_run_id: 1,
    turn_id: "$turns.turn_id",
    turn: "$turns"
  }}
]).forEach(doc => {
  print("Test ID:", doc.test_id);
  print("Turn ID:", doc.turn_id);
  print("Evaluation:", doc.evaluation_run_id);
  print("\nTurn Details:");
  print("  Start:", doc.turn.start_ms, "ms");
  print("  End:", doc.turn.end_ms, "ms");
  print("\nLatency Breakdown:");
  var lat = doc.turn.latency;
  print("  first_outbound_ms:", lat.first_outbound_ms);
  print("  last_outbound_ms:", lat.last_outbound_ms);
  print("  first_response_ms:", lat.first_response_ms);
  print("  first_audio_response_ms:", lat.first_audio_response_ms);
  print("  first_text_response_ms:", lat.first_text_response_ms);
  print("  last_audio_response_ms:", lat.last_audio_response_ms);
  print("\nCalculated Latencies:");
  print("  latency_ms (audio):", lat.latency_ms);
  print("  text_latency_ms:", lat.text_latency_ms);
  print("  first_chunk_latency_ms:", lat.first_chunk_latency_ms);
  print("  audio_duration_ms:", lat.audio_duration_ms);
  print("\nEvent Counts:");
  print("  audio_event_count:", lat.audio_event_count);
  print("  text_event_count:", lat.text_event_count);
})
```

### Find Maximum Latency Turn

Locate the slowest response:

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$match: {"turns.latency.latency_ms": {$gte: 15000, $lt: 16000}}},
  {$sort: {"turns.latency.latency_ms": -1}},
  {$limit: 1},
  {$project: {
    test_id: 1,
    evaluation_run_id: 1,
    turn_id: "$turns.turn_id",
    turn: "$turns"
  }}
]).forEach(doc => {
  print("Test ID:", doc.test_id);
  print("Turn ID:", doc.turn_id);
  print("Evaluation:", doc.evaluation_run_id);
  print("\nLatency Breakdown:");
  var lat = doc.turn.latency;
  print("  latency_ms (audio):", lat.latency_ms, "← MAX");
  print("  text_latency_ms:", lat.text_latency_ms);
  print("  first_chunk_latency_ms:", lat.first_chunk_latency_ms);
  print("  audio_duration_ms:", lat.audio_duration_ms);
  print("  audio_event_count:", lat.audio_event_count);
  print("  text_event_count:", lat.text_event_count);
})
```

---

## 5. Test-Specific Analysis

### Analyze All Turns in a Specific Test

Useful for understanding performance patterns:

```javascript
db.test_runs.aggregate([
  {$match: {test_id: "fatigue_exam"}},
  {$limit: 1},
  {$unwind: "$turns"},
  {$match: {"turns.latency.latency_ms": {$gte: 0}}},
  {$project: {
    turn_id: "$turns.turn_id",
    participant: "$turns.source_language",
    audio_duration: "$turns.latency.audio_duration_ms",
    latency: "$turns.latency.latency_ms",
    audio_events: "$turns.latency.audio_event_count",
    text_events: "$turns.latency.text_event_count",
    source_length: {$strLenCP: "$turns.source_text"}
  }},
  {$sort: {latency: -1}}
]).forEach(doc => {
  print(doc.turn_id.padEnd(20),
        "Lang:", doc.participant,
        "| Audio:", (doc.audio_duration + "ms").padEnd(8),
        "| Latency:", (doc.latency + "ms").padEnd(8),
        "| Events: A=" + doc.audio_events + " T=" + doc.text_events,
        "| Text len:", doc.source_length);
})
```

### Check for Barge-In Tests

Find tests with barge-in behavior:

```javascript
db.test_runs.aggregate([
  {$match: {test_id: /barge_in/}},
  {$unwind: "$turns"},
  {$project: {
    test_id: 1,
    turn_id: "$turns.turn_id",
    latency_ms: "$turns.latency.latency_ms",
    first_audio_response_ms: "$turns.latency.first_audio_response_ms"
  }},
  {$sort: {latency_ms: 1}},
  {$limit: 10}
]).forEach(doc => printjson(doc))
```

---

## 6. Environment and Target System Analysis

### Latency by Environment

Compare latency across environments:

```javascript
db.evaluation_runs.aggregate([
  {$lookup: {
    from: "test_runs",
    localField: "_id",
    foreignField: "evaluation_run_id",
    as: "tests"
  }},
  {$unwind: "$tests"},
  {$unwind: "$tests.turns"},
  {$match: {"tests.turns.latency.latency_ms": {$gte: 0}}},
  {$group: {
    _id: {
      environment: "$environment",
      target_system: "$target_system"
    },
    count: {$sum: 1},
    avg_latency: {$avg: "$tests.turns.latency.latency_ms"},
    min_latency: {$min: "$tests.turns.latency.latency_ms"},
    max_latency: {$max: "$tests.turns.latency.latency_ms"}
  }},
  {$sort: {avg_latency: -1}}
]).forEach(doc => {
  print("Environment:", doc._id.environment);
  print("Target System:", doc._id.target_system);
  print("  Count:", doc.count, "turns");
  print("  Avg:", Math.round(doc.avg_latency), "ms");
  print("  Min:", doc.min_latency, "ms");
  print("  Max:", doc.max_latency, "ms");
  print("");
})
```

---

## 7. Validation Queries

### Verify Latency Calculation

Manually verify the latency formula:

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$match: {"turns.turn_id": "doctor_turn_1"}},
  {$limit: 1},
  {$project: {
    test_id: 1,
    turn_id: "$turns.turn_id",
    last_outbound: "$turns.latency.last_outbound_ms",
    first_audio: "$turns.latency.first_audio_response_ms",
    stored_latency: "$turns.latency.latency_ms",
    calculated_latency: {
      $subtract: [
        "$turns.latency.first_audio_response_ms",
        "$turns.latency.last_outbound_ms"
      ]
    },
    matches: {
      $eq: [
        "$turns.latency.latency_ms",
        {$subtract: [
          "$turns.latency.first_audio_response_ms",
          "$turns.latency.last_outbound_ms"
        ]}
      ]
    }
  }}
]).forEach(doc => {
  print("Test:", doc.test_id);
  print("Turn:", doc.turn_id);
  print("Formula: first_audio_response_ms - last_outbound_ms");
  print("Calculation:", doc.first_audio, "-", doc.last_outbound, "=", doc.calculated_latency);
  print("Stored value:", doc.stored_latency);
  print("Matches:", doc.matches ? "✓" : "✗");
})
```

### Count Valid vs Invalid Latencies

Check data quality:

```javascript
db.test_runs.aggregate([
  {$project: {
    total_turns: {$size: "$turns"},
    turns_with_latency: {
      $size: {
        $filter: {
          input: "$turns",
          as: "turn",
          cond: {$ne: ["$$turn.latency.latency_ms", null]}
        }
      }
    },
    negative_latencies: {
      $size: {
        $filter: {
          input: "$turns",
          as: "turn",
          cond: {$lt: ["$$turn.latency.latency_ms", 0]}
        }
      }
    }
  }},
  {$group: {
    _id: null,
    total_turns: {$sum: "$total_turns"},
    with_latency: {$sum: "$turns_with_latency"},
    negative: {$sum: "$negative_latencies"}
  }}
]).forEach(doc => {
  print("Total turns:", doc.total_turns);
  print("With latency data:", doc.with_latency);
  print("Negative latencies:", doc.negative);
  print("Valid latencies:", doc.with_latency - doc.negative);
  print("Coverage:", Math.round((doc.with_latency / doc.total_turns) * 100) + "%");
})
```

---

## Common Debugging Patterns

### Pattern 1: Progressive Latency Degradation

If latency increases during a conversation, check:

```javascript
db.test_runs.aggregate([
  {$match: {test_id: "YOUR_TEST_ID"}},
  {$unwind: {path: "$turns", includeArrayIndex: "turn_index"}},
  {$match: {"turns.latency.latency_ms": {$gte: 0}}},
  {$project: {
    turn_index: 1,
    turn_id: "$turns.turn_id",
    latency_ms: "$turns.latency.latency_ms",
    audio_duration: "$turns.latency.audio_duration_ms",
    latency_ratio: {
      $divide: [
        "$turns.latency.latency_ms",
        "$turns.latency.audio_duration_ms"
      ]
    }
  }},
  {$sort: {turn_index: 1}}
]).forEach(doc => {
  print("Turn", doc.turn_index + ":", doc.turn_id,
        "| Latency:", doc.latency_ms + "ms",
        "| Ratio:", Math.round(doc.latency_ratio * 100) + "%");
})
```

### Pattern 2: Audio vs Text Event Mismatch

Check if audio is being streamed properly:

```javascript
db.test_runs.aggregate([
  {$unwind: "$turns"},
  {$match: {"turns.latency.audio_event_count": {$exists: true}}},
  {$group: {
    _id: {
      audio_events: "$turns.latency.audio_event_count"
    },
    count: {$sum: 1},
    avg_text_events: {$avg: "$turns.latency.text_event_count"},
    avg_latency: {$avg: "$turns.latency.latency_ms"}
  }},
  {$sort: {"_id.audio_events": 1}}
]).forEach(doc => {
  print("Audio events:", doc._id.audio_events);
  print("  Turn count:", doc.count);
  print("  Avg text events:", Math.round(doc.avg_text_events));
  print("  Avg latency:", Math.round(doc.avg_latency), "ms");
  print("");
})
```

---

## Tips and Best Practices

### 1. Always Filter Null Values

```javascript
{$match: {"turns.latency.latency_ms": {$ne: null}}}
```

### 2. Use Limits When Exploring

Add `{$limit: 10}` to avoid overwhelming output:

```javascript
{$limit: 10}
```

### 3. Format Output for Readability

Use `padEnd()` for aligned columns:

```javascript
print(doc.turn_id.padEnd(20), "Latency:", (doc.latency + "ms").padEnd(8));
```

### 4. Save Complex Queries

For frequently used queries, save them in a `.js` file:

```bash
mongosh vt_metrics --quiet < queries/latency_stats.js
```

---

## Related Documentation

- [VAD Latency Explained](VAD_LATENCY_EXPLAINED.md) - Understanding latency metrics
- [Timing Debug Guide](TIMING_DEBUG_GUIDE.md) - Debugging timing issues
- [Storage README](../storage/README.md) - MongoDB schema documentation

---

## Troubleshooting

### Query Returns Empty Results

Check if data exists:

```javascript
db.test_runs.countDocuments()
db.test_runs.countDocuments({"turns.latency.latency_ms": {$exists: true}})
```

### Performance Issues

Add indexes for frequently queried fields:

```javascript
db.test_runs.createIndex({"turns.latency.latency_ms": 1})
db.test_runs.createIndex({"test_id": 1})
```

### Aggregation Errors

Use `explain()` to debug:

```javascript
db.test_runs.explain("executionStats").aggregate([...])
```
