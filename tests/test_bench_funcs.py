"""Tests for bench/funcs.py: function spans and function-level gold from a patch."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bench"))

import funcs  # noqa: E402

SRC = """import os

X = 1


def alpha(a):
    b = a + 1
    return b


class Box:
    size = 3

    @property
    def area(self):
        return self.size ** 2

    def grow(self, n):
        def inner():
            return n
        self.size += inner()
        return self


def omega():
    return 0
"""

PATCH = """diff --git a/pkg/mod.py b/pkg/mod.py
index 111..222 100644
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -6,3 +6,3 @@ X = 1
 def alpha(a):
-    b = a + 1
+    b = a + 2
     return b
@@ -18,4 +18,5 @@ class Box:
     def grow(self, n):
         def inner():
             return n
+        n += 1
         self.size += inner()
@@ -23,3 +24,7 @@ class Box:


+def added():
+    return 1
+
+
 def omega():
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


def test_function_spans_cover_methods_and_decorators():
    spans = funcs.functions(SRC)
    assert [s[0] for s in spans] == ["alpha", "Box.area", "Box.grow", "omega"]
    assert dict((s[0], (s[1], s[2])) for s in spans)["Box.area"] == (14, 16)      # starts at the decorator
    assert funcs.function_at(spans, 20) == "Box.grow"                             # nested function -> its parent
    assert funcs.function_at(spans, 4) is None
    assert funcs.functions("def broken(:\n") is None


def test_gold_functions_from_patch():
    gold, module_only = funcs.gold_functions(PATCH, lambda p: SRC if p == "pkg/mod.py" else None)
    # a changed line, a line inserted inside a method; a function added between two others is not gold
    assert gold == ["pkg/mod.py::alpha", "pkg/mod.py::Box.grow"]
    assert module_only == []


def test_module_level_change_has_no_gold_function():
    patch = "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -3,1 +3,1 @@\n-X = 1\n+X = 2\n"
    assert funcs.gold_functions(patch, lambda p: SRC) == ([], ["m.py"])


def test_chunks_split_functions_and_module_remainder():
    ch = dict(funcs.chunks("m.py", SRC))
    assert set(ch) == {"m.py::alpha", "m.py::Box.area", "m.py::Box.grow", "m.py::omega", "m.py::<module>"}
    assert "inner" in ch["m.py::Box.grow"] and "size = 3" in ch["m.py::<module>"]
    assert funcs.chunks("e.py", "") == [("e.py::<module>", "")]
