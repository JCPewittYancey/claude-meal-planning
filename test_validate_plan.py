#!/usr/bin/env python3
"""Regression tests for validate_plan.py. Run: python3 test_validate_plan.py

Builds a plan that passes, then applies one mutation per rule and checks that the
expected violation (or input error) appears. No third-party packages needed.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "validate_plan.py")

PARAMS = [
    ("recency_days", "28", "Script"), ("new_recipe_min", "1", "Script"),
    ("variety_breakfast_per_person", "2", "Script"), ("variety_lunch_per_person", "2", "Script"),
    ("variety_dinner_per_person", "3", "Script"), ("rating_exclude_at_or_below", "3", "Script"),
    ("no_breakfast_days", "Sunday", "Script"), ("restaurant_lunch_days", "Sunday", "Script"),
    ("default_quick_dinner_days", "Monday", "Script"), ("quick_dinner_raw_max_minutes", "20", "Script"),
    ("time_buffer_multiplier", "1.5", "Script"), ("instant_pot_max_uses_per_day", "1", "Script"),
    ("seafood_allowed_people", "James", "Script"), ("simple_assembly_people", "James", "Script"),
    ("simple_prep_people", "James", "Script"), ("simple_prep_hands_on_max_minutes", "10", "Script"),
    ("simple_prep_raw_total_max_minutes", "30", "Script"),
    ("protein_shake_recipe_name", "Premier Protein Shake", "Script"),
    ("jacob_calories_target", "none", "Script"), ("jacob_calories_tolerance", "none", "Script"),
    ("jacob_protein_min", "60", "Script"), ("jacob_protein_soft_min", "none", "Script"),
    ("jacob_fiber_min", "25", "Script"), ("jacob_fiber_max", "40", "Script"),
    ("jacob_restaurant_meal_calories", "none", "Script"),
    ("jacob_protein_shakes_default_per_day", "none", "Script"),
    ("jacob_protein_shakes_max_per_day", "none", "Script"),
    ("james_calories_target", "1600", "Script"), ("james_calories_tolerance", "100", "Script"),
    ("james_protein_min", "none", "Script"), ("james_protein_soft_min", "120", "Script"),
    ("james_fiber_min", "25", "Script"), ("james_fiber_max", "40", "Script"),
    ("james_restaurant_meal_calories", "750", "Script"),
    ("james_protein_shakes_default_per_day", "1", "Script"),
    ("james_protein_shakes_max_per_day", "2", "Script"),
    ("outing_min_gap_days", "21", "Claude"), ("perishable_days", "Monday, Tuesday, Wednesday", "Claude"),
]


def params(overrides=None, drop=None, extra=None):
    rows = []
    for k, v, by in PARAMS:
        if drop and k == drop:
            continue
        if overrides and k in overrides:
            v = overrides[k]
        rows.append({"key": k, "value": v, "checked_by": by})
    if extra:
        rows.append(extra)
    return rows


RECIPES = [
    # Jacob breakfast / lunch / dinner, all shareable data
    {"id": 1, "name": "Oat Bake", "category": "Breakfast", "times_used": 3, "last_used": "2026-09-01",
     "last_used_jacob": "2026-09-01", "last_used_james": None, "rating_jacob": "5", "rating_james": "Untried",
     "retired": False, "notes": "", "primary_appliance": "Oven", "quick_dinner": False,
     "prep_time_minutes": 15, "cook_time_minutes": 45, "prep_time_minutes_raw": 10, "cook_time_minutes_raw": 30,
     "protein_per_serving": 20, "fiber_per_serving": 8, "calories_per_serving": 400,
     "fasting_lvl_1": True, "fasting_lvl_2": False, "fasting_lvl_3": False, "fasting_lvl_4": False, "fasting_lvl_5": False},
    {"id": 2, "name": "Bean Bowl", "category": "Lunch", "times_used": 2, "last_used": "2026-09-01",
     "last_used_jacob": "2026-09-01", "last_used_james": None, "rating_jacob": "4", "rating_james": "Untried",
     "retired": False, "notes": "", "primary_appliance": "Stovetop", "quick_dinner": False,
     "prep_time_minutes": 15, "cook_time_minutes": 15, "prep_time_minutes_raw": 10, "cook_time_minutes_raw": 10,
     "protein_per_serving": 20, "fiber_per_serving": 10, "calories_per_serving": 450,
     "fasting_lvl_1": True, "fasting_lvl_2": True, "fasting_lvl_3": True, "fasting_lvl_4": False, "fasting_lvl_5": False},
    {"id": 3, "name": "Quick Tofu Stir Fry", "category": "Dinner", "times_used": 4, "last_used": "2026-09-01",
     "last_used_jacob": "2026-09-01", "last_used_james": "2026-09-01", "rating_jacob": "5", "rating_james": "5",
     "retired": False, "notes": "", "primary_appliance": "Stovetop", "quick_dinner": True,
     "prep_time_minutes": 15, "cook_time_minutes": 15, "prep_time_minutes_raw": 10, "cook_time_minutes_raw": 10,
     "protein_per_serving": 25, "fiber_per_serving": 8, "calories_per_serving": 500,
     "fasting_lvl_1": True, "fasting_lvl_2": True, "fasting_lvl_3": True, "fasting_lvl_4": False, "fasting_lvl_5": False},
    # James solo items
    {"id": 10, "name": "Yogurt Bowl", "category": "Breakfast", "times_used": 2, "last_used": "2026-09-01",
     "last_used_jacob": None, "last_used_james": "2026-09-01", "rating_jacob": "Untried", "rating_james": "4",
     "retired": False, "notes": "", "primary_appliance": "None", "quick_dinner": False,
     "prep_time_minutes": 8, "cook_time_minutes": 0, "prep_time_minutes_raw": 5, "cook_time_minutes_raw": 0,
     "protein_per_serving": 30, "fiber_per_serving": 8, "calories_per_serving": 350,
     "fasting_lvl_1": True, "fasting_lvl_2": False, "fasting_lvl_3": False, "fasting_lvl_4": False, "fasting_lvl_5": False},
    {"id": 11, "name": "Slow Lentil Stew", "category": "Dinner", "times_used": 1, "last_used": "2026-08-01",
     "last_used_jacob": None, "last_used_james": "2026-08-01", "rating_jacob": "Untried", "rating_james": "4",
     "retired": False, "notes": "", "primary_appliance": "Stovetop", "quick_dinner": False,
     "prep_time_minutes": 30, "cook_time_minutes": 60, "prep_time_minutes_raw": None, "cook_time_minutes_raw": None,
     "protein_per_serving": 25, "fiber_per_serving": 12, "calories_per_serving": 450,
     "fasting_lvl_1": True, "fasting_lvl_2": True, "fasting_lvl_3": True, "fasting_lvl_4": False, "fasting_lvl_5": False},
    {"id": 20, "name": "Premier Protein Shake", "category": "Snack", "times_used": 9, "last_used": "2026-09-01",
     "last_used_jacob": None, "last_used_james": "2026-09-01", "rating_jacob": "Untried", "rating_james": "4",
     "retired": False, "notes": "Exempt from recency rule", "primary_appliance": "None", "quick_dinner": False,
     "prep_time_minutes": None, "cook_time_minutes": None, "prep_time_minutes_raw": None, "cook_time_minutes_raw": None,
     "protein_per_serving": 30, "fiber_per_serving": 1, "calories_per_serving": 160,
     "fasting_lvl_1": True, "fasting_lvl_2": False, "fasting_lvl_3": False, "fasting_lvl_4": False, "fasting_lvl_5": False},
]


def meal(slot, eaters, name, source="database", rid=None, **kw):
    m = {"slot": slot, "eaters": eaters, "name": name, "source": source, "recipe_id": rid,
         "servings_consumed": {p: 1 for p in eaters}, "instant_pot": False}
    m.update(kw)
    return m


def james_simple_dinner():
    return meal("Dinner", ["James"], "Rockfish + broccoli + rice", "simple", contains_seafood=True,
                nutrition_per_serving={"calories": 640, "protein": 40, "fiber": 10})


def base_plan():
    # One Monday; tests mutate it. Restaurant test: 750 assumed + 160 shake + 640 dinner = 1550.
    return {
        "plan_monday": "2026-11-16",
        "people": ["Jacob", "James"],
        "quick_dinner_requested_days": [],
        "restaurant_lunch_requested_days": [],
        "days": [{
            "date": "2026-11-16", "day": "Monday",
            "fasting_effective_level": {"Jacob": 0, "James": 0},
            "meals": [
                meal("Breakfast", ["Jacob"], "Oat Bake", rid=1),
                meal("Breakfast", ["James"], "Yogurt Bowl", rid=10),
                meal("Lunch", ["Jacob"], "Bean Bowl", rid=2, servings_consumed={"Jacob": 2}),
                meal("Lunch", ["James"], "Fish Lunch (new)", "new_web", raw_prep_minutes=5, raw_total_minutes=20,
                     contains_seafood=True, nutrition_per_serving={"calories": 450, "protein": 35, "fiber": 10}),
                meal("Snack", ["James"], "Premier Protein Shake", rid=20),
                meal("Dinner", ["Jacob"], "Quick Tofu Stir Fry", rid=3),
                james_simple_dinner(),
            ],
        }],
    }


def run(plan, prm=None):
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, obj in (("params", prm if prm is not None else params()), ("plan", plan),
                          ("recipes", RECIPES), ("snacks", [])):
            p = os.path.join(d, name + ".json")
            with open(p, "w") as f:
                json.dump(obj, f)
            paths.append(p)
        r = subprocess.run([sys.executable, SCRIPT] + paths, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


def meals(plan):
    return plan["days"][0]["meals"]


def find(plan, name):
    return next(m for m in meals(plan) if m["name"] == name)


CASES = []


def case(desc, expect_code, expect_text):
    def wrap(fn):
        CASES.append((desc, fn, expect_code, expect_text))
        return fn
    return wrap


@case("baseline passes", 0, "PASSED")
def _(p):
    return p, None


@case("seafood served to Jacob", 1, "contains seafood but is served to Jacob")
def _(p):
    find(p, "Quick Tofu Stir Fry")["contains_seafood"] = True
    return p, None


@case("simple assembly meal for Jacob", 1, "simple assembly meal served to Jacob")
def _(p):
    m = find(p, "Bean Bowl")
    m.update(source="simple", recipe_id=None, nutrition_per_serving={"calories": 400, "protein": 30, "fiber": 12})
    return p, None


@case("James solo meal over raw total (DB fallback from adjusted)", 1, "min raw total (> 30)")
def _(p):
    m = find(p, "Rockfish + broccoli + rice")
    m.update(source="database", recipe_id=11, name="Slow Lentil Stew", contains_seafood=False,
             nutrition_per_serving=None)
    meals(p)[:] = [x for x in meals(p) if x["slot"] != "Dinner" or x["eaters"] != ["James"]] + [m]
    p["days"][0]["day"] = "Tuesday"   # avoid the quick-dinner rule masking this
    return p, None


@case("James solo new recipe over hands-on prep", 1, "min raw prep (> 10)")
def _(p):
    find(p, "Fish Lunch (new)")["raw_prep_minutes"] = 15
    return p, None


@case("simple dinner counts as quick on Monday", 0, "PASSED")
def _(p):
    return p, None


@case("dinner variety is per person", 1, "Variety (James): 4 distinct dinner")
def _(p):
    base = copy.deepcopy(p["days"][0])
    p["days"] = []
    for i, dn in enumerate(["Tuesday", "Wednesday", "Thursday", "Friday"]):
        d = copy.deepcopy(base)
        d["day"] = dn
        d["date"] = f"2026-11-{17 + i}"
        for m in d["meals"]:
            if m["slot"] == "Dinner" and m["eaters"] == ["James"]:
                m["name"] = f"Simple dinner {i}"
        p["days"].append(d)
    return p, None


@case("three shakes is over the max", 1, "3 protein shakes (max 2)")
def _(p):
    find(p, "Premier Protein Shake")["servings_consumed"]["James"] = 3
    return p, None


@case("two shakes is a call-out warning, not a violation", None, "call this day out")
def _(p):
    find(p, "Premier Protein Shake")["servings_consumed"]["James"] = 2
    return p, None


@case("restaurant calories come from parameters", None, "James: 1550")
def _(p):
    p["days"][0]["day"] = "Sunday"
    keep = [m for m in meals(p) if m["slot"] not in ("Breakfast", "Lunch")]
    keep.append(meal("Lunch", ["Jacob", "James"], "Restaurant", "restaurant"))
    meals(p)[:] = keep
    return p, None


@case("Sunday breakfast forbidden via no_breakfast_days", 1, "no breakfast may be planned on Sunday")
def _(p):
    p["days"][0]["day"] = "Sunday"
    return p, None


@case("recency window comes from parameters", 1, "within 120 days")
def _(p):
    return p, params({"recency_days": "120"})


@case("rating cutoff comes from parameters", 1, "rated this recipe 4 (at or below 4)")
def _(p):
    return p, params({"rating_exclude_at_or_below": "4"})


@case("one-off quick day from the plan request", 1, "quick dinner required on Tuesday")
def _(p):
    p["days"][0]["day"] = "Tuesday"
    p["quick_dinner_requested_days"] = ["Tuesday"]
    find(p, "Quick Tofu Stir Fry")["recipe_id"] = 2   # Bean Bowl: quick_dinner false
    return p, None


@case("missing Script parameter is an input error", 2, "recency_days is missing")
def _(p):
    return p, params(drop="recency_days")


@case("unknown Script parameter is an input error", 2, "does not know it")
def _(p):
    return p, params(extra={"key": "max_fish_dinners", "value": "2", "checked_by": "Script"})


@case("unknown Claude parameter is ignored", 0, "PASSED")
def _(p):
    return p, params(extra={"key": "max_fish_dinners", "value": "2", "checked_by": "Claude"})


@case("unreadable value is an input error", 2, "cannot read value 'four weeks'")
def _(p):
    return p, params({"recency_days": "four weeks"})


@case("unknown person in a people list is an input error", 2, "not a known person")
def _(p):
    return p, params({"seafood_allowed_people": "James, Bob"})


def main():
    failures = 0
    for desc, fn, code, text in CASES:
        plan, prm = fn(copy.deepcopy(base_plan()))
        rc, out = run(plan, prm)
        ok = (code is None or rc == code) and text in out
        print(f"{'PASS' if ok else 'FAIL'}  {desc}")
        if not ok:
            failures += 1
            print(f"      expected code {code} and text {text!r}; got code {rc}\n" +
                  "\n".join("      " + line for line in out.splitlines()))
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
