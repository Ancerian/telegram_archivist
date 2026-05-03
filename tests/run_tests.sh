#!/bin/bash
cd "$(dirname "$0")"

if python3 -c "import pytest" >/dev/null 2>&1; then
  python3 -m pytest test_core.py -v
else
  echo "pytest не встановлено, запускаю простий fallback-runner"
  python3 - <<'PY'
import test_core

failed = 0
tests = [
    (name, func)
    for name, func in vars(test_core).items()
    if name.startswith("test_") and callable(func)
]

for name, func in tests:
    try:
        func()
        print(f"PASSED {name}")
    except Exception as exc:
        failed += 1
        print(f"FAILED {name}: {exc}")

print(f"\n{len(tests) - failed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
PY
fi
