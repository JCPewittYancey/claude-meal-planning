"""Tests for validate_plan.py 2.9.0: side_ids on any meal, not only assembly meals.

Run from the repo root:  python3 tests/test_sides_on_any_meal.py
"""
import json, subprocess, sys, tempfile, os

HERE = os.path.dirname(os.path.abspath(__file__))
VALIDATOR = os.path.join(HERE, "..", "validate_plan.py")
P = lambda k, v, c="Script": {"key": k, "value": v, "checked_by": c}
PARAMS = [P("recency_days","28"),P("new_recipe_min","0"),P("variety_breakfast_per_person","2"),
 P("variety_lunch_per_person","2"),P("variety_dinner_per_person","3"),P("rating_exclude_at_or_below","3"),
 P("no_breakfast_days","none"),P("restaurant_lunch_days","none"),P("default_quick_dinner_days","none"),
 P("time_buffer_multiplier","1.5"),P("instant_pot_max_uses_per_day","1"),P("seafood_allowed_people","A"),
 P("simple_assembly_people","A"),P("simple_prep_people","none"),P("simple_prep_hands_on_max_minutes","10"),
 P("simple_prep_raw_total_max_minutes","30"),P("flavor_variety_people","none"),P("quick_dinner_people","none"),
 P("protein_shake_recipe_name","Shake"),P("a_calories_target","none"),P("a_calories_tolerance","none"),
 P("a_protein_min","none"),P("a_protein_soft_min","none"),P("a_fiber_min","none"),P("a_fiber_max","none"),
 P("a_restaurant_meal_calories","none"),P("a_protein_shakes_default_per_day","none"),
 P("a_protein_shakes_max_per_day","none")]
def rec(i, name, cat):
    return {"id": i, "name": name, "category": cat, "source": "Web", "flavor_key": None, "last_used": None,
            "last_used_a": None, "times_used": 0, "rating_a": "Untried", "retired": False, "notes": "",
            "works_for_a": "Yes", "shared_meal_safe": "Yes", "batch_cook_or_fresh": "Fresh Daily",
            "primary_appliance": "Stovetop", "quick_dinner": False, "prep_time_minutes": 8, "cook_time_minutes": 15,
            "prep_time_minutes_raw": 5, "cook_time_minutes_raw": 10, "protein_per_serving": 30,
            "fiber_per_serving": 1, "calories_per_serving": 250, "fasting_lvl_1": True, "fasting_lvl_2": True,
            "fasting_lvl_3": True, "fasting_lvl_4": True, "fasting_lvl_5": True}
RECIPES = [rec(1, "Sourced fish", "Dinner"), rec(2, "Steamed broccoli", "Side"), rec(3, "Pasta bake", "Dinner")]
def plan(meal_extra):
    meal = {"slot": "Dinner", "eaters": ["A"], "name": "Sourced fish", "source": "database", "recipe_id": 1,
            "servings_consumed": {"A": 1}, "multiplier": None, "eggs_in_recipe": 0, "instant_pot": False,
            "contains_seafood": True, "user_requested": False}
    meal.update(meal_extra)
    return {"plan_monday": "2026-11-16", "scope": "full", "people": ["A"], "quick_dinner_requested_days": [],
            "restaurant_lunch_requested_days": [], "days": [{"date": "2026-11-16", "day": "Monday",
            "fasting_effective_level": {"A": 0}, "meals": [meal]}]}
def run(p):
    d = tempfile.mkdtemp()
    files = {"params": PARAMS, "plan": p, "recipes": RECIPES, "snack": [], "flavor": []}
    paths = {}
    for k, v in files.items():
        paths[k] = os.path.join(d, k + ".json"); json.dump(v, open(paths[k], "w"))
    r = subprocess.run([sys.executable, VALIDATOR, paths["params"], paths["plan"], paths["recipes"],
                        paths["snack"], paths["flavor"]], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr
NUT = {"nutrition_per_serving": {"calories": 370, "protein": 40, "fiber": 10}}
cases = [
    ("sourced recipe with valid sides and whole-meal nutrition passes", {"side_ids": [2], **NUT}, 0, None),
    ("sourced recipe with sides but no whole-meal nutrition fails", {"side_ids": [2]}, 1, "no whole-meal nutrition_per_serving"),
    ("non-Side row used as a side fails", {"side_ids": [3], **NUT}, 1, "is not a Side row"),
    ("missing side id fails", {"side_ids": [99], **NUT}, 1, "not found in recipes.json"),
    ("sourced recipe without sides is unchanged", {}, 0, None),
]
failed = 0
for name, extra, want_code, want_text in cases:
    code, out = run(plan(extra))
    ok = code == want_code and (want_text is None or want_text in out)
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failed += 1; print(out)
sys.exit(1 if failed else 0)
