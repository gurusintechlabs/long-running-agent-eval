**Stage 5: specification audit**

Before we sign this off, audit the specification against the plugin itself.

1. Go back to the decompiled code and re-check every active claim in `analysis/claims.jsonl`. Retract
   claims that are wrong and add corrected ones (new ids). Add claims for behaviour you missed.
2. Update `analysis/SPEC.md` to match.
3. Update the rewrite and its tests for every claim you changed or added.
4. Write `analysis/AUDIT.md`: how many claims you checked, retracted, corrected and added, and why.
