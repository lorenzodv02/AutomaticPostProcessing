# -*- coding: utf-8 -*-
"""
Runner di test senza dipendenze esterne.

Uso:  python tests/run_tests.py
Con pytest installato gli stessi test girano con:  pytest -q
"""

import importlib
import os
import sys
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MODULES = (
    "tests.test_config_bridge",
    "tests.test_parser_synthetic",
    "tests.test_rules_thresholds",
    "tests.test_version",
    "tests.test_packaging",
    "tests.test_discovery",
    "tests.test_ai_vision",
    "tests.test_render_utils",
    "tests.test_brand",
    "tests.test_meta_locator",
)


def main() -> int:
    passed = 0
    failures = []
    for module_name in MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            print("FAIL  %s  (import)" % module_name)
            failures.append((module_name, traceback.format_exc()))
            continue
        for attribute in sorted(dir(module)):
            if not attribute.startswith("test_"):
                continue
            function = getattr(module, attribute)
            if not callable(function):
                continue
            label = "%s.%s" % (module_name, attribute)
            try:
                function()
            except Exception:
                print("FAIL  %s" % label)
                failures.append((label, traceback.format_exc()))
            else:
                passed += 1
                print("PASS  %s" % label)

    print("")
    print("Test superati: %d | falliti: %d" % (passed, len(failures)))
    for label, trace in failures:
        print("")
        print("=" * 70)
        print("FALLITO:", label)
        print("-" * 70)
        print(trace.rstrip())
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
