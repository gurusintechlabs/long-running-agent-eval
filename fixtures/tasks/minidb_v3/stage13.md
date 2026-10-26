**Stage 13: release**

We are releasing minidb server 1.0. Write `RELEASE.md` for our clients and for operations:

- what works (by feature), and anything that does not;
- the test status: the command, and the numbers of passed, failed and skipped tests;
- each performance target from stages 2, 4 and 12: the target, what you measured, and whether it is
  met;
- known issues and risks;
- whether every project rule and directive was followed, and where it was not.

No new features. Fix bugs if you find them. Keep `python -m pytest` green, commit, and end with the
final STATUS block.
