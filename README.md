# claude-meal-planning

Validation script for the household meal-planner Claude skill.

The meal-planner skill downloads `validate_plan.py` from this repo at the start of every plan, so a commit here takes effect in the next planning chat (allow a few minutes for GitHub's raw-file cache). Household rules and every number the script uses live in the "Household Meal Planning" Claude Doc, not here. The script refuses to run if the doc's Parameters table and the script disagree on which Script parameters exist.

## Files

- `validate_plan.py`: the validator. Usage and input formats are in its docstring.
- `test_validate_plan.py`: regression tests. Run `python3 test_validate_plan.py` before committing a change; every case must pass.

## Changing the script

1. Edit `validate_plan.py` and bump `VERSION`.
2. If you added a Script parameter, add its row to the doc's Parameters table and to `PARAMS` in the tests.
3. Add a test case for the new rule, run the tests, commit to `main`.

This repo is public because the skill fetches it without credentials. Do not commit anything private.
