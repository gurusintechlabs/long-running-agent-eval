"""The v2 stdin protocol answers a query (every minidb v3 reference stage keeps it)."""
import json
import os
import subprocess


def test_python_m_minidb_answers_a_query():
    out = subprocess.run([os.environ["LRAE_PYTHON"], "-m", "minidb"], input="SELECT 1 + 1;\n", text=True,
                         capture_output=True, cwd=os.environ["LRAE_WORKSPACE"], timeout=30)
    assert json.loads(out.stdout.splitlines()[0]) == {"ok": True, "columns": ["?column?"], "rows": [[2]]}, out
