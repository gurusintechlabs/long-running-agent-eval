**Stage 5: change request: corrections to the specification**

Our analyst reviewed the specification again and committed corrections in `spec/CHANGES-1.md`. Each
entry replaces claims of `spec/claims.jsonl` with new claims, given in full in that file under new ids.

1. Apply every correction to the replacement: change the code and the tests for every claim that was
   replaced. Tests for a replaced claim are named after its new id, and no test keeps the old id.
2. Update `analysis/rewrite_map.json` (claim lists, status): each new id replaces the old one.
3. Write `analysis/CHANGES-APPLIED.md`: for each entry in `spec/CHANGES-1.md`, naming the old and the
   new claim ids, what you changed, and anything you could not apply.
