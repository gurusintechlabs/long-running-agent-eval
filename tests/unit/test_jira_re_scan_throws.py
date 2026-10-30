"""jira-re JC2: analyst/scan_throws.py finds `throw`s that the decompiler dropped, by comparing the exceptions a
class constructs and throws in its bytecode (javap) with the `throw` statements in its decompiled source
(docs/phase-JC1-summary.md: Vineflower silently dropped four throws in the API)."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parents[2] / "fixtures" / "tasks" / "jira_re"
sys.path.insert(0, str(TASK / "analyst"))

import scan_throws as st  # noqa: E402

JAVAP = """\
Compiled from "Gate.java"
public class com.acme.Gate {
  public com.acme.Gate();
    Code:
       0: aload_0
       1: invokespecial #1                  // Method java/lang/Object."<init>":()V
       4: return

  public void check(java.lang.String);
    Code:
       0: aload_1
       1: ifnonnull     23
       4: new           #7                  // class java/lang/IllegalArgumentException
       7: dup
       8: new           #9                  // class java/lang/StringBuilder
      11: dup
      12: invokespecial #11                 // Method java/lang/StringBuilder."<init>":()V
      15: invokevirtual #12                 // Method java/lang/StringBuilder.toString:()Ljava/lang/String;
      18: invokespecial #13                 // Method java/lang/IllegalArgumentException."<init>":(Ljava/lang/String;)V
      21: athrow
      22: aload_2
      23: athrow
      24: new           #15                 // class java/lang/AssertionError
      27: dup
      28: invokespecial #16                 // Method java/lang/AssertionError."<init>":()V
      31: athrow
      32: invokestatic  #17                 // Method com/acme/Gate.fail:()Ljava/lang/RuntimeException;
      35: athrow
      36: new           #9                  // class java/lang/StringBuilder
      39: dup
      40: invokespecial #11                 // Method java/lang/StringBuilder."<init>":()V
      43: invokespecial #18                 // Method error:(Ljava/lang/StringBuilder;)Ljava/lang/RuntimeException;
      46: athrow
}
Compiled from "Gate.java"
class com.acme.Gate$Inner {
  void run();
    Code:
       0: new           #2                  // class java/lang/IllegalStateException
       3: dup
       4: invokespecial #3                  // Method java/lang/IllegalStateException."<init>":()V
       7: athrow
       8: new           #2                  // class java/lang/IllegalStateException
      11: dup
      12: invokespecial #3                  // Method java/lang/IllegalStateException."<init>":()V
      15: athrow
}
Compiled from "Other.java"
public final class com.acme.Other {
  static {};
    Code:
       0: new           #4                  // class com/acme/Other$Oops
       3: dup
       4: invokespecial #5                  // Method com/acme/Other$Oops."<init>":()V
       7: athrow
}
"""


def test_bytecode_throws_counts_constructed_throws_per_top_level_class():
    got = st.bytecode_throws(JAVAP)
    # the rethrow (aload; athrow) and the assertion are not counted; exceptions built by helpers (static, or
    # private through invokespecial) count by the helper's name
    assert got == {"com.acme.Gate": Counter({"IllegalArgumentException": 1, "IllegalStateException": 2,
                                             "fail()": 1, "error()": 1}),
                   "com.acme.Other": Counter({"Other$Oops": 1})}


def test_source_throws_reads_java_and_kotlin_forms():
    java = 'if (x) throw new IllegalArgumentException("a");\n throw new java.lang.IllegalStateException();\n' \
           'throw new Other.Oops();\n throw e;\n// throw new Nope();'
    kotlin = 'throw IllegalStateException("k")\n'
    assert st.source_throws(java) == Counter({"IllegalArgumentException": 1, "IllegalStateException": 1,
                                              "Oops": 1, "Nope": 1})
    assert st.source_throws(kotlin) == Counter({"IllegalStateException": 1})


def test_compare_reports_throws_missing_from_the_source(tmp_path):
    src = tmp_path / "src" / "com" / "acme"
    src.mkdir(parents=True)
    (src / "Gate.java").write_text('throw new IllegalArgumentException("x"); throw new IllegalStateException();'
                                   ' throw fail(); throw error(b);')
    (src / "Other.java").write_text("throw new Other.Oops();")
    got = st.compare(st.bytecode_throws(JAVAP), tmp_path / "src")
    assert got == [st.Missing("com.acme.Gate", "IllegalStateException", 2, 1)]


def test_compare_reports_classes_with_no_source(tmp_path):
    (tmp_path / "src").mkdir()
    got = st.compare({"com.acme.Gate": Counter({"IllegalStateException": 1})}, tmp_path / "src")
    assert got == [st.Missing("com.acme.Gate", "IllegalStateException", 1, None)]


def test_synthetic_throws_are_ignored():
    text = JAVAP.replace("java/lang/IllegalArgumentException", "java/lang/MatchException")
    assert "IllegalArgumentException" not in st.bytecode_throws(text)["com.acme.Gate"]
    assert "MatchException" not in st.bytecode_throws(text)["com.acme.Gate"]


FACTORY_JAVAP = """\
public class com.acme.Res {
  private java.lang.Object find(java.lang.String);
    Code:
       0: getstatic     #1                  // Field com/acme/Errors.BAD:Lcom/acme/Errors;
       3: ldc           #2                  // String no such source
       5: invokevirtual #3                  // Method com/acme/Errors.withMessage:(Ljava/lang/String;)Lcom/acme/Failure;
       8: athrow
  private void rethrow(java.lang.Exception);
    Code:
       0: aload_1
       1: athrow
  private void viaAccessor();
    Code:
       0: invokestatic  #6                  // Method com/acme/Res.access$500:()Ljava/lang/RuntimeException;
       3: athrow
  private void kotlinCheck();
    Code:
       0: invokestatic  #4                  // Method kotlin/jvm/internal/Intrinsics.throwNpe:()Ljava/lang/Object;
       3: checkcast     #5                  // class java/lang/RuntimeException
       6: athrow
}
"""


def test_bytecode_throws_counts_exceptions_built_by_a_method_call():
    """`throw Errors.BAD.withMessage(...)`: nothing is constructed here, and the decompiler drops these too.
    A plain rethrow, a compiler's `access$n` accessor and Kotlin's own intrinsics are not counted."""
    assert st.bytecode_throws(FACTORY_JAVAP)["com.acme.Res"] == Counter({"withMessage()": 1})


def test_a_dropped_factory_throw_is_reported_and_a_visible_one_is_not(tmp_path):
    src = tmp_path / "src" / "com" / "acme"
    src.mkdir(parents=True)
    (src / "Res.java").write_text("class Res { Object find(String s) { return null; } }")
    got = st.compare(st.bytecode_throws(FACTORY_JAVAP), tmp_path / "src")
    assert [(m.cls, m.exception, m.bytecode, m.source) for m in got] == [("com.acme.Res", "withMessage()", 1, 0)]
    (src / "Res.java").write_text('class Res { Object find(String s) {\n  throw Errors.BAD\n    .withMessage("no"); } }')
    assert st.compare(st.bytecode_throws(FACTORY_JAVAP), tmp_path / "src") == []
