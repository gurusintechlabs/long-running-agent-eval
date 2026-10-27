**Stage 5: change request: corrections to the specification**

Our analyst reviewed the specification again and committed corrections in `spec/CHANGES-1.md`. Each
entry retracts or replaces claims, or adds new ones; the ids it names refer to `spec/claims.jsonl`.

1. Apply every correction to the replacement: change the code and the tests for every claim that was
   retracted, corrected or added. Tests for a corrected claim are named after its new id.
2. Update `analysis/rewrite_map.json` (claim lists, status).
3. Write `analysis/CHANGES-APPLIED.md`: for each entry in `spec/CHANGES-1.md`, what you changed, and
   anything you could not apply.
