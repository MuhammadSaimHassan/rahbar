#!/usr/bin/env bash
set -euo pipefail

case "${1:?usage: ci-checks.sh lint|test}" in
  lint)
    python -m ruff check api indexer eval corpus scripts/check_fixture_answers.py scripts/operational_demo.py scripts/check_real_acceptance.py scripts/check_real_operations.py
    (cd api && python -m mypy app)
    (cd indexer && python -m mypy pipeline)
    ;;
  test)
    export RETRIEVER=stub LLM_PROVIDER=stub
    (cd api && python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=60)
    (cd indexer && python -m pytest)
    python -m pytest corpus/tests eval/tests
    python eval/prepare_golden.py --check-lock
    ;;
  *) exit 2 ;;
esac
