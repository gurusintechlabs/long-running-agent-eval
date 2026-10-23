**Stage 1: the behavioural specification**

Turn your understanding of the plugin into a specification that someone who has never seen the
decompiled code could implement from.

## 1.1 `analysis/SPEC.md`

For each module: when it runs (the trigger: a workflow transition, a REST call, an event, a schedule,
a page view ...), its inputs, what it decides or computes, its outputs and side effects, the error
cases, and any configuration it reads. Describe behaviour, not code: no decompiled code, no method
bodies.

## 1.2 `analysis/claims.jsonl`

One JSON object per line, one testable behaviour per claim:

```json
{"id": "C-001", "module": "<module key, or null for shared behaviour>",
 "behaviour": "When ..., the plugin ...",
 "evidence": ["com.example.Foo#validate"],
 "confidence": "high|medium|low", "status": "active"}
```

Every module must have at least one active claim. Evidence must name the classes or methods where you
saw the behaviour. Ids are permanent: if a claim turns out to be wrong, set `"status": "retracted"` and
add a new claim, never reuse or delete an id.

Commit both files.
