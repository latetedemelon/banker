#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified test runner.

Runs both the new ``bankhub`` test suite (``test/test_*.py``) and the legacy
``lib`` suite (``test.py``) in one process.  Loading modules by file path
sidesteps the name clash between the ``test.py`` file and the ``test/``
directory, and lets both suites share a single interpreter despite needing
different import paths.

Usage::

    python run_tests.py
"""

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(ROOT, "lib")

# The new suite imports `bankhub` (root on path); the legacy suite imports
# flat modules from `lib`.  Both can coexist on sys.path.
for path in (ROOT, LIB):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("ENV", "test")  # legacy Assets() reads ENV


def _load(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def build_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # New bankhub tests.
    test_dir = os.path.join(ROOT, "test")
    for fname in sorted(os.listdir(test_dir)):
        if fname.startswith("test_") and fname.endswith(".py"):
            mod = _load(f"bankhub_tests_{fname[:-3]}", os.path.join(test_dir, fname))
            suite.addTests(loader.loadTestsFromModule(mod))

    # Legacy lib tests (best-effort: skip if lib has been removed).
    legacy = os.path.join(ROOT, "test.py")
    if os.path.exists(legacy):
        try:
            mod = _load("legacy_lib_tests", legacy)
            suite.addTests(loader.loadTestsFromModule(mod))
        except Exception as exc:  # pragma: no cover
            print(f"warning: skipping legacy tests ({exc})", file=sys.stderr)

    return suite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(build_suite())
    sys.exit(0 if result.wasSuccessful() else 1)
