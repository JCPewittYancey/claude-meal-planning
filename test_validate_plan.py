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
    ("default_quick_dinner_days", "Monday", "Script"), 
    ("time_buffer_multiplier", "1.5", "Script"), ("instant_pot_max_uses_per_day", "1", "Script"),
    ("seafood_allowed_people", "James", "Script"), ("simple_assembly_people", "James", "Script"),
    ("simple_prep_people", "James", "Script"), ("simple_prep_hands_on_max_minutes", "10", "Script"),
    ("simple_prep_raw_total_max_minutes", "30", "Script"), ("flavor_variety_people", "James", "Script"),
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
    # James protein preparations (source Assembly) and a side
    {"id": 30, "name": "Lemon pepper rockfish", "category": "Lunch/Dinner", "source": "Assembly",
     "flavor_key": "Rockfish | Lemon Pepper",
     "times_used": 2, "last_used": "2026-11-02", "last_used_jacob": None, "last_used_james": "2026-11-02",
     "rating_jacob": "Untried", "rating_james": "4", "retired": False, "notes": "", "primary_appliance": "Oven",
     "quick_dinner": True, "prep_time_minutes": 8, "cook_time_minutes": 18, "prep_time_minutes_raw": 5,
     "cook_time_minutes_raw": 12, "protein_per_serving": 35, "fiber_per_serving": 0, "calories_per_serving": 180,
     "fasting_lvl_1": True, "fasting_lvl_2": True, "fasting_lvl_3": False, "fasting_lvl_4": False, "fasting_lvl_5": False},
    {"id": 31, "name": "Cajun tilapia", "category": "Lunch/Dinner", "source": "Assembly", "flavor_key": "tilapia | cajun",
     "times_used": 0, "last_used": None, "last_used_jacob": None, "last_used_james": None,
     "rating_jacob": "Untried", "rating_james": "Untried", "retired": False, "notes": "", "primary_appliance": "Oven",
     "quick_dinner": True, "prep_time_minutes": 8, "cook_time_minutes": 30, "prep_time_minutes_raw": 5,
     "cook_time_minutes_raw": 20, "protein_per_serving": 35, "fiber_per_serving": 0, "calories_per_serving": 170,
     "fasting_lvl_1": True, "fasting_lvl_2": True, "fasting_lvl_3": False, "fasting_lvl_4": False, "fasting_lvl_5": False},
    {"id": 40, "name": "Steam-in-bag broccoli", "category": "Side", "source": "Assembly", "flavor_key": None,
     "times_used": 5, "last_used": "2026-11-09", "last_used_jacob": None, "last_used_james": "2026-11-09",
     "rating_jacob": "Untried", "rating_james": "Untried", "retired": False, "notes": "Exempt from recency rule",
     "primary_appliance": "Microwave", "quick_dinner": False, "prep_time_minutes": 0, "cook_time_minutes": 8,
     "prep_time_minutes_raw": 0, "cook_time_minutes_raw": 5, "protein_per_serving": 3, "fiber_per_serving": 3,
     "calories_per_serving": 35, "fasting_lvl_1": True, "fasting_lvl_2": True, "fasting_lvl_3": True,
     "fasting_lvl_4": True, "fasting_lvl_5": True},
]


for _r in RECIPES:
    _r.setdefault("works_for_jacob", "Yes")
    _r.setdefault("works_for_james", "Yes")
    _r.setdefault("shared_meal_safe", "Yes")


def meal(slot, eaters, name, source="database", rid=None, **kw):
    m = {"slot": slot, "eaters": eaters, "name": name, "source": source, "recipe_id": rid,
         "servings_consumed": {p: 1 for p in eaters}, "instant_pot": False}
    m.update(kw)
    return m


def james_simple_dinner():
    return meal("Dinner", ["James"], "Garlic herb salmon", "simple", contains_seafood=True,
                flavor_key="salmon | garlic herb", side_ids=[40],
                nutrition_per_serving={"calories": 640, "protein": 40, "fiber": 10})


FLAVOR_HISTORY = [
    {"flavor_key": "rockfish | lemon pepper", "week_of": "2026-11-02", "person": "James"},
    {"flavor_key": "tofu | teriyaki", "week_of": "2026-11-09", "person": "Both"},
]


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
                     contains_seafood=True, flavor_key="tilapia | blackened",
                     nutrition_per_serving={"calories": 450, "protein": 35, "fiber": 10}),
                meal("Snack", ["James"], "Premier Protein Shake", rid=20),
                meal("Dinner", ["Jacob"], "Quick Tofu Stir Fry", rid=3),
                james_simple_dinner(),
            ],
        }],
    }


def run(plan, prm=None, flavor=None, recipes=None):
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, obj in (("params", prm if prm is not None else params()), ("plan", plan),
                          ("recipes", RECIPES if recipes is None else recipes), ("snacks", []),
                          ("flavor", FLAVOR_HISTORY if flavor is None else flavor)):
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
    m.update(source="simple", recipe_id=None, side_ids=[40],
             nutrition_per_serving={"calories": 400, "protein": 30, "fiber": 12})
    return p, None


@case("James solo meal over raw total (DB fallback from adjusted)", 1, "min raw total (> 30)")
def _(p):
    m = find(p, "Garlic herb salmon")
    m.update(source="database", recipe_id=11, name="Slow Lentil Stew", contains_seafood=False,
             nutrition_per_serving=None, flavor_key="lentil | curry", side_ids=None)
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
                m["flavor_key"] = f"salmon | flavor {i}"
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


@case("stored protein preparation is subject to recency, whatever the sides", 1, "James last had this 2026-11-02")
def _(p):
    find(p, "Garlic herb salmon").update(recipe_id=30, name="Lemon pepper rockfish", flavor_key=None)
    return p, None


@case("new protein preparation does not satisfy the new-recipe minimum", 1, "New-recipe minimum")
def _(p):
    m = find(p, "Fish Lunch (new)")
    m.update(source="database", recipe_id=10, name="Yogurt Bowl", contains_seafood=False,
             nutrition_per_serving=None, flavor_key="yogurt | vanilla")
    find(p, "Garlic herb salmon").update(recipe_id=31, name="Cajun tilapia", flavor_key=None)
    return p, None


@case("simple meal pointing at a non-Assembly row", 1, "is not an Assembly row")
def _(p):
    find(p, "Garlic herb salmon")["recipe_id"] = 3
    return p, None


@case("side id that is not a Side row", 1, "is not a Side row")
def _(p):
    find(p, "Garlic herb salmon")["side_ids"] = [2]
    return p, None


@case("same protein and flavor in a sourced solo recipe is blocked", 1, "had 'rockfish | lemon pepper'")
def _(p):
    find(p, "Fish Lunch (new)")["flavor_key"] = "Rockfish|lemon  pepper"
    return p, None


@case("flavor eaten in a shared meal counts for James's solo meals", 1, "had 'tofu | teriyaki'")
def _(p):
    find(p, "Fish Lunch (new)").update(flavor_key="tofu | teriyaki", contains_seafood=False)
    return p, None


@case("same protein with a different flavor is fine", 0, "PASSED")
def _(p):
    find(p, "Fish Lunch (new)")["flavor_key"] = "rockfish | cajun"
    return p, None


@case("flavor rule does not apply to Jacob", 0, "PASSED")
def _(p):
    find(p, "Bean Bowl")["flavor_key"] = "tofu | teriyaki"
    return p, None


@case("missing flavor key on a solo meal is a warning", 0, "flavor variety unchecked")
def _(p):
    find(p, "Fish Lunch (new)").pop("flavor_key")
    return p, None


@case("variety counts protein preparations, not side combinations", 0, "PASSED")
def _(p):
    base = copy.deepcopy(p["days"][0])
    p["days"] = []
    for i, dn in enumerate(["Tuesday", "Wednesday", "Thursday", "Friday"]):
        d = copy.deepcopy(base)
        d.update(day=dn, date=f"2026-11-{17 + i}")
        for m in d["meals"]:
            if m["slot"] == "Dinner" and m["eaters"] == ["James"]:
                m["new_sides"] = [f"Side {i}"]
                m["side_ids"] = []
        p["days"].append(d)
    return p, None


def _three_breakfast_days(p, pin_first, pin_second=False, requested=True):
    base = copy.deepcopy(p["days"][0])
    p["days"] = []
    names = [("Oat Bake", 1), ("Bean Bowl", 2), ("Quick Tofu Stir Fry", 3)]
    for i, dn in enumerate(["Monday", "Tuesday", "Wednesday"]):
        d = copy.deepcopy(base)
        d.update(day=dn, date=f"2026-11-{16 + i}")
        m = next(x for x in d["meals"] if x["slot"] == "Breakfast" and x["eaters"] == ["Jacob"])
        n, rid = names[i] if not (pin_second and i == 1) else names[0]
        m.update(name=n, recipe_id=rid)
        if (i == 0 and pin_first) or (pin_second and i == 1):
            m.update(user_requested=requested, user_pinned_single_day=True)
        p["days"].append(d)
    return p


@case("three breakfast recipes without a pin exceeds the limit", 1, "Variety (Jacob): 3 distinct breakfast")
def _(p):
    return _three_breakfast_days(p, False), None


@case("a single-day pin is excluded from variety", None, "excluded from variety limits")
def _(p):
    return _three_breakfast_days(p, True), None


@case("pinned single-day meal really avoids the variety violation", None, "PINCHECK")
def _(p):
    return _three_breakfast_days(p, True), None


@case("same recipe pinned on two days is a violation", 1, "is pinned on 2 days")
def _(p):
    return _three_breakfast_days(p, True, pin_second=True), None


@case("pin without user_requested is a violation", 1, "user_requested is not")
def _(p):
    return _three_breakfast_days(p, True, requested=False), None


def _with_recipe(rid, **fields):
    rs = copy.deepcopy(RECIPES)
    next(r for r in rs if r["id"] == rid).update(fields)
    return rs


@case("works_for = No for an eater is a violation", 1, "works_for_jacob = No, but Jacob is eating it")
def _(p):
    return p, None, _with_recipe(3, works_for_jacob="No")


@case("works_for = Modified is a warning, not a violation", 0, "state Jacob's modification")
def _(p):
    return p, None, _with_recipe(3, works_for_jacob="Modified")


@case("works_for = No for the other person does not matter for a solo meal", 0, "PASSED")
def _(p):
    return p, None, _with_recipe(3, works_for_james="No")


@case("shared_meal_safe = No on a shared meal is a violation", 1, "shared_meal_safe = No but is planned as a shared meal")
def _(p):
    find(p, "Quick Tofu Stir Fry")["eaters"] = ["Jacob", "James"]
    find(p, "Quick Tofu Stir Fry")["servings_consumed"] = {"Jacob": 1, "James": 1}
    meals(p)[:] = [m for m in meals(p) if m["name"] != "Garlic herb salmon"]
    return p, None, _with_recipe(3, shared_meal_safe="No")


@case("missing works_for field in the dump is a warning", 0, "missing from the dump")
def _(p):
    rs = copy.deepcopy(RECIPES)
    next(r for r in rs if r["id"] == 3).pop("works_for_jacob")
    return p, None, rs


@case("person in the plan with no parameter rows is an input error", 2, "has no per-person rows")
def _(p):
    p["people"] = ["Jacob", "James", "Sam"]
    return p, None


@case("a new household member with only some rows is an input error", 2, "sam_fiber_max is missing")
def _(p):
    return p, params(extra={"key": "sam_fiber_min", "value": "25", "checked_by": "Script"})


@case("a new household member with a full set of rows is accepted", 0, "PASSED")
def _(p):
    rows = params()
    for k, v, by in PARAMS:
        if k.startswith("jacob_"):
            rows.append({"key": "sam_" + k[len("jacob_"):], "value": v, "checked_by": by})
    return p, rows


@case("new recipe over the fixed quick-dinner time on a quick day", 1, "raw total is 35 min (> 20)")
def _(p):
    find(p, "Quick Tofu Stir Fry").update(source="new_web", recipe_id=None, raw_total_minutes=35,
                                          nutrition_per_serving={"calories": 500, "protein": 25, "fiber": 8})
    return p, None


@case("partial plan skips the household new-recipe minimum", 0, "Partial plan (one person's half)")
def _(p):
    p["scope"] = "partial"
    p["people"] = ["James"]
    for d in p["days"]:
        d["meals"] = [m for m in d["meals"] if "James" in m["eaters"]]
        for m in d["meals"]:
            if m["source"] == "new_web":
                m.update(source="database", recipe_id=10, name="Yogurt Bowl", contains_seafood=False,
                         nutrition_per_serving=None, flavor_key="yogurt | vanilla")
    return p, None


@case("partial plan with a shared meal does not count the other person", 0, "PASSED")
def _(p):
    p["scope"] = "partial"
    p["people"] = ["Jacob"]
    for d in p["days"]:
        d["meals"] = [m for m in d["meals"] if "Jacob" in m["eaters"]]
    find(p, "Quick Tofu Stir Fry").update(eaters=["Jacob", "James"], servings_consumed={"Jacob": 1, "James": 1})
    return p, None


def main():
    failures = 0
    for desc, fn, code, text in CASES:
        res = fn(copy.deepcopy(base_plan()))
        plan, prm = res[0], res[1]
        rc, out = run(plan, prm, recipes=res[2] if len(res) > 2 else None)
        if text == "PINCHECK":
            ok = "Variety (Jacob): 3 distinct breakfast" not in out and "Variety (Jacob): 2 distinct breakfast" not in out
        else:
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
