# claude-meal-planning

Validation script for the household meal-planner Claude skill.

The meal-planner skill downloads `validate_plan.py` (and, for split planning, `merge_plans.py`) from this repo at the start of every plan, so a commit here takes effect in the next planning chat (allow a few minutes for GitHub's raw-file cache). Household rules and every number the script uses live in the "Household Meal Planning" Claude Doc, not here. The script refuses to run if the doc's Parameters table and the script disagree on which Script parameters exist.

## Files

- `validate_plan.py`: the validator. Usage and input formats are in its docstring.
- `merge_plans.py`: merges two people's half-plans (split planning) into one plan for the validator. Usage and the draft format are in its docstring.
- `test_validate_plan.py`, `test_merge_plans.py`, and `tests/test_sides_on_any_meal.py`: regression tests. Run all three from the repo root before committing a change; every case must pass:

  ```
  python3 test_validate_plan.py
  python3 test_merge_plans.py
  python3 tests/test_sides_on_any_meal.py
  ```

## Changing the script

1. Edit `validate_plan.py` and bump `VERSION`.
2. If you added a Script parameter, add its row to the doc's Parameters table and to `PARAMS` in the tests.
3. Add a test case for the new rule, run the tests, commit to `main`.

This repo is public because the skill fetches it without credentials. Do not commit anything private.
