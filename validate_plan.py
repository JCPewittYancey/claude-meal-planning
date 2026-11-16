#!/usr/bin/env python3
"""Deterministic validator for weekly meal plans.

VERSION is printed on every run so the plan session can report which copy ran.

Usage:
    python3 validate_plan.py params.json plan.json recipes.json snack_history.json flavor_history.json

All five files are required; pass [] for a history file with no rows.

Exit codes: 0 = passed, 1 = hard-rule violations, 2 = bad input (parameters or files).

------------------------------------------------------------------------------
params.json: the Parameters table from the "Household Meal Planning" Claude Doc,
copied VERBATIM, one object per table row, every row included (Script and
Claude rows alike). Do not convert types, split lists, or drop rows; this
script parses the cell text itself so nothing is reinterpreted in transit.

[
  {"key": "recency_days", "value": "28", "checked_by": "Script"},
  {"key": "default_quick_dinner_days", "value": "Monday", "checked_by": "Script"},
  {"key": "outing_min_gap_days", "value": "21", "checked_by": "Claude"},
  ...
]

People are discovered from the table: anyone with any per-person row ("<name>_fiber_min" and so
on) is a household member, and every member needs the full set of per-person rows (PERSON_KEYS),
"none" where unused. Adding someone to the household is a doc edit, not a code change.
Rules: every key in SCRIPT_SCHEMA must be present and marked Script; a Script
row whose key this script does not know is an error (the doc is ahead of the
code); a known key marked Claude is an error. Claude rows are otherwise ignored.
Values: integers, decimals, comma-separated lists, or "none".

------------------------------------------------------------------------------
plan.json: the draft plan.
{
  "plan_monday": "YYYY-MM-DD",
  "scope": "full",                       # "partial" for one person's half in split planning:
                                         # people lists only that person; household-wide checks
                                         # wait for the merged plan (see merge_plans.py)
  "people": ["PersonA", "PersonB"],
  "quick_dinner_requested_days": [],     # one-off quick days for THIS plan only.
                                         # default_quick_dinner_days come from params. Quick days
                                         # apply only to dinners eaten by someone in
                                         # quick_dinner_people (a shared dinner counts).
  "restaurant_lunch_requested_days": [], # one-off restaurant lunches the user asked for
  "days": [
    {
      "date": "YYYY-MM-DD",
      "day": "Monday",
      "away": {"PersonB": ["Breakfast", "Lunch", "Snack"]},   # optional: meals missed out of town;
                                                            # that person's floors are not enforced that day
      "fasting_effective_level": {"PersonA": 0, "PersonB": 3},  # 0 = no fast. Write the level AFTER
            # applying the household fasting exceptions in the doc. Restrictions an exception does
            # not lift must be checked by hand.
      "meals": [
        {
          "slot": "Dinner",                  # Breakfast | Lunch | Snack | Dinner
          "eaters": ["PersonB"],
          "recipe_id": 12,                   # null for new_web / restaurant / leftovers. For a simple
                                             # assembly meal: the id of its PROTEIN PREPARATION row
                                             # (source Assembly, e.g. "Cajun tilapia"); null if new.
                                             # For assembly meals, "name" is the protein preparation name.
          "side_ids": [40, 41],              # ids of existing Side rows served with this meal. Any meal
                                             # may carry them (an assembly meal, or a sourced recipe served
                                             # with plain sides). Every food counted in nutrition_per_serving
                                             # must be the recipe itself or one of these sides, or it never
                                             # reaches the grocery list, the PDF, or history.
          "new_sides": ["Roasted zucchini"], # sides not yet in the database (any meal)
          "flavor_key": "tilapia | cajun",   # "protein | flavor profile". Taken from the recipe row when
                                             # it has one; give it here for new recipes and rows without one.
                                             # Required for solo meals of flavor_variety_people.
          "name": "Lemon Garlic Tofu Stir Fry",
          "source": "database",              # database | new_web | restaurant | simple | leftovers
          "servings_consumed": {"PersonB": 1},
          "multiplier": 0.5,                 # scaling vs base yield; null if n/a
          "eggs_in_recipe": 0,               # eggs in BASE recipe; null/0 if none
          "instant_pot": false,              # true if prep uses the Instant Pot that day (incl. rice)
          "contains_seafood": false,         # REQUIRED true on any meal containing seafood as the
                                             # household doc defines it
          "fasting_flags": {"1": true, "2": true, "3": false},
                                             # REQUIRED for new_web meals and for every assembly meal
                                             # (whole meal incl. sides) on fasting days; other database
                                             # recipes use their DB flags
          "raw_prep_minutes": 8,             # new_web only: raw hands-on prep (needed for simple-prep)
          "raw_total_minutes": 25,           # new_web only: raw total (quick dinner, simple-prep)
          "nutrition_per_serving": {"calories": 320, "protein": 30, "fiber": 6},
                                             # new_web, leftovers, EVERY assembly meal, and any meal with
                                             # side_ids or new_sides (whole meal at the portions served,
                                             # main plus sides). Restaurant calories come
                                             # from the <person>_restaurant_meal_calories parameter.
          "nutrition_estimated": false,
          "user_requested": false,           # true only if the user asked for this recipe this week;
                                             # overrides recency and flavor variety (warnings)
          "proposal_id": "p1",               # split planning only: marks the first planner's fallback
                                             # meal for a shared-meal proposal (see merge_plans.py);
                                             # ignored by this script
          "user_pinned_single_day": false    # true only when the user said they are having this exact
                                             # thing for this meal on ONE day ("yogurt for breakfast
                                             # today"). Excluded from variety limits. Requires
                                             # user_requested. The same recipe pinned for the same
                                             # person and slot on 2+ days is a violation. Unpinned
                                             # uses of the recipe elsewhere still count.
        }
      ]
    }
  ]
}

------------------------------------------------------------------------------
recipes.json: rows for every recipe_id in the plan, joined to the per-person view:
  SELECT r.id, r.name, r.category, r.source, r.flavor_key, r.last_used, v.last_used_jacob, v.last_used_james,
         r.times_used, r.rating_jacob, r.rating_james, r.retired, r.notes,
         r.works_for_jacob, r.works_for_james, r.shared_meal_safe,
         r.batch_cook_or_fresh, r.primary_appliance, r.quick_dinner,
         r.prep_time_minutes, r.cook_time_minutes,
         r.prep_time_minutes_raw, r.cook_time_minutes_raw,
         r.protein_per_serving, r.fiber_per_serving, r.calories_per_serving,
         r.fasting_lvl_1, r.fasting_lvl_2, r.fasting_lvl_3, r.fasting_lvl_4, r.fasting_lvl_5
  FROM recipes r JOIN recipe_last_used_by_person v ON v.recipe_id = r.id
  WHERE r.id IN (...all recipe_ids AND side_ids in the plan...);

flavor_history.json: flavor keys eaten by flavor_variety_people in the window:
  SELECT r.flavor_key, h.week_of, h.person
  FROM meal_plan_history h JOIN recipes r ON r.id = h.recipe_id
  WHERE r.flavor_key IS NOT NULL
  AND h.person IN ([each person in flavor_variety_people], 'Both')
  AND h.week_of >= '[plan_monday minus recency_days]';

snack_history.json:
  SELECT recipe_id, week_of, person FROM meal_plan_history
  WHERE meal_slot = 'Snack' AND week_of >= '[plan_monday minus recency_days]';
"""

import json
import re
import sys
from datetime import date, timedelta

VERSION = "2.9.0"

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAIN_SLOTS = ("Breakfast", "Lunch", "Dinner")
NON_RECIPE_SOURCES = ("restaurant", "simple", "leftovers")
EGG_EPSILON = 0.001
QUICK_RAW_MAX = 20  # fixed: a new recipe is a quick dinner if its raw total is at most this

# key -> type. Types: int, int_or_none, float, days, people, text
SCRIPT_SCHEMA = {
    "recency_days": "int",
    "new_recipe_min": "int",
    "variety_breakfast_per_person": "int",
    "variety_lunch_per_person": "int",
    "variety_dinner_per_person": "int",
    "rating_exclude_at_or_below": "int",
    "no_breakfast_days": "days",
    "restaurant_lunch_days": "days",
    "default_quick_dinner_days": "days",
    "time_buffer_multiplier": "float",
    "instant_pot_max_uses_per_day": "int",
    "seafood_allowed_people": "people",
    "simple_assembly_people": "people",
    "simple_prep_people": "people",
    "simple_prep_hands_on_max_minutes": "int",
    "simple_prep_raw_total_max_minutes": "int",
    "flavor_variety_people": "people",
    "quick_dinner_people": "people",
    "protein_shake_recipe_name": "text",
}
PERSON_KEYS = {
    "calories_target": "int_or_none",
    "calories_tolerance": "int_or_none",
    "protein_min": "int_or_none",
    "protein_soft_min": "int_or_none",
    "fiber_min": "int_or_none",
    "fiber_max": "int_or_none",
    "restaurant_meal_calories": "int_or_none",
    "protein_shakes_default_per_day": "int_or_none",
    "protein_shakes_max_per_day": "int_or_none",
}
PERSON_KEY_RE = re.compile(r"^([a-z][a-z0-9]*)_(" + "|".join(PERSON_KEYS) + r")$")
KNOWN_PEOPLE = []  # filled from the Parameters table by load_params


class InputError(Exception):
    pass


def _split(raw):
    return [s.strip() for s in raw.split(",") if s.strip()]


def parse_value(key, typ, raw):
    if not isinstance(raw, str):
        raw = str(raw)
    s = raw.strip()
    is_none = s.lower() in ("none", "")
    try:
        if typ == "int":
            if is_none:
                raise ValueError("required")
            v = int(s)
            if v < 0:
                raise ValueError("negative")
            return v
        if typ == "int_or_none":
            if is_none:
                return None
            v = int(s)
            if v < 0:
                raise ValueError("negative")
            return v
        if typ == "float":
            v = float(s)
            if v <= 0:
                raise ValueError("not positive")
            return v
        if typ == "days":
            if is_none:
                return set()
            out = set()
            for d in _split(s):
                match = [w for w in WEEKDAYS if w.lower() == d.lower()]
                if not match:
                    raise ValueError(f"'{d}' is not a weekday")
                out.add(match[0])
            return out
        if typ == "people":
            if is_none:
                return set()
            out = set()
            for p in _split(s):
                match = [k for k in KNOWN_PEOPLE if k.lower() == p.lower()]
                if not match:
                    raise ValueError(f"'{p}' is not a known person ({', '.join(KNOWN_PEOPLE)})")
                out.add(match[0])
            return out
        if typ == "text":
            if is_none:
                raise ValueError("required")
            return s
    except ValueError as e:
        raise InputError(f"Parameter {key}: cannot read value {raw!r} as {typ} ({e}).")
    raise InputError(f"Parameter {key}: unknown type {typ}.")


def load_params(path):
    rows = load(path)
    if not isinstance(rows, list):
        raise InputError("params.json must be a list of {key, value, checked_by} rows.")
    errors = []
    seen = {}
    found = sorted({m.group(1) for r in rows
                    for m in [PERSON_KEY_RE.match((r.get("key") or "").strip())] if m})
    if not found:
        raise InputError("No household members found: the Parameters table has no <name>_calories_target rows.")
    KNOWN_PEOPLE[:] = [p.capitalize() for p in found]
    schema = dict(SCRIPT_SCHEMA)
    for person in found:
        for k, ktype in PERSON_KEYS.items():
            schema[f"{person}_{k}"] = ktype
    for r in rows:
        key = (r.get("key") or "").strip()
        by = (r.get("checked_by") or "").strip().lower()
        if not key:
            errors.append(f"Row with no key: {r}")
            continue
        if key in seen:
            errors.append(f"Parameter {key} appears more than once.")
            continue
        seen[key] = (r.get("value"), by)
        if by == "script" and key not in schema:
            errors.append(
                f"Parameter {key} is marked Script but this validator (v{VERSION}) does not know it. "
                "The validator must be updated before this row can be used."
            )
        if key in schema and by != "script":
            errors.append(f"Parameter {key} is read by the validator but is marked {by or 'blank'}, not Script.")
    params = {}
    for key, typ in schema.items():
        if key not in seen:
            errors.append(f"Parameter {key} is missing from the doc's Parameters table.")
            continue
        try:
            params[key] = parse_value(key, typ, seen[key][0])
        except InputError as e:
            errors.append(str(e))
    if errors:
        raise InputError("\n".join(errors))
    return params, schema


def parse_date(s):
    return date.fromisoformat(s)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise InputError(f"Cannot read {path}: {e}")


def is_exempt(recipe):
    return "exempt from recency rule" in (recipe.get("notes") or "").lower()


def raw_minutes(rec, which, mult):
    """Raw prep or cook minutes for a DB recipe; falls back to adjusted / multiplier."""
    raw = rec.get(f"{which}_time_minutes_raw")
    if raw is not None:
        return raw
    adj = rec.get(f"{which}_time_minutes")
    if adj is None:
        return None
    return adj / mult


def person_target(params, person, key):
    return params.get(f"{person.lower()}_{key}")


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        sys.exit(2)
    print(f"VALIDATOR v{VERSION}")
    try:
        P, SCHEMA = load_params(sys.argv[1])
        plan = load(sys.argv[2])
        recipes = {r["id"]: r for r in load(sys.argv[3])}
        snack_history = load(sys.argv[4])
        flavor_history = load(sys.argv[5])
        people = plan["people"]
        for p in people:
            if p not in KNOWN_PEOPLE:
                raise InputError(f"plan.people contains {p!r}, who has no per-person rows in the Parameters table.")
        plan_monday = parse_date(plan["plan_monday"])
    except InputError as e:
        print("\nINPUT ERROR (nothing was validated):\n")
        print(e)
        sys.exit(2)
    except KeyError as e:
        print(f"\nINPUT ERROR (nothing was validated): plan.json is missing {e}.")
        sys.exit(2)

    print("PARAMETERS USED:")
    for k in SCHEMA:
        v = P[k]
        if isinstance(v, set):
            v = ", ".join(sorted(v)) or "none"
        print(f"  {k} = {'none' if v is None else v}")
    print()

    violations = []
    warnings = []
    recency = timedelta(days=P["recency_days"])
    cutoff = P["rating_exclude_at_or_below"]
    variety_limits = {
        "Breakfast": P["variety_breakfast_per_person"],
        "Lunch": P["variety_lunch_per_person"],
        "Dinner": P["variety_dinner_per_person"],
    }
    quick_days = set(plan.get("quick_dinner_requested_days", [])) | P["default_quick_dinner_days"]
    rest_lunch_ok = set(plan.get("restaurant_lunch_requested_days", []))
    mult_buf = P["time_buffer_multiplier"]
    shake_name = P["protein_shake_recipe_name"].lower()

    variety = {p: {s: set() for s in MAIN_SLOTS} for p in people}
    pinned_seen = {}  # (person, slot, name) -> [days]
    new_recipes = set()
    day_report = []
    new_snacks_warned = set()
    recent_snack = {}
    for h in snack_history:
        if parse_date(h["week_of"]) >= plan_monday - recency:
            who = h.get("person") or "Both"
            ppl = set(people) if who == "Both" else {who}
            recent_snack.setdefault(h["recipe_id"], set()).update(ppl)
    fallback_warned = set()

    def norm_key(k):
        if not k:
            return None
        parts = [" ".join(x.lower().split()) for x in str(k).split("|")]
        return " | ".join(parts)

    recent_flavor = {p: {} for p in people}  # person -> {flavor_key: latest week_of}
    for h in flavor_history:
        k = norm_key(h.get("flavor_key"))
        if not k or parse_date(h["week_of"]) < plan_monday - recency:
            continue
        who = h.get("person") or "Both"
        for p in (people if who == "Both" else [who]):
            if p in recent_flavor:
                prev = recent_flavor[p].get(k)
                if prev is None or h["week_of"] > prev:
                    recent_flavor[p][k] = h["week_of"]

    def last_used_for(rec, person):
        key = f"last_used_{person.lower()}"
        if key in rec:
            return rec.get(key)
        if rec.get("id") not in fallback_warned:
            fallback_warned.add(rec.get("id"))
            warnings.append(f"Recipe {rec.get('name')}: no per-person last_used in dump; using overall last_used.")
        return rec.get("last_used")

    def bad_rating(r):
        if r is None:
            return False
        try:
            return int(str(r).strip()) <= cutoff
        except ValueError:
            return False  # 'Untried', 'Unrated', ''

    for day in plan["days"]:
        dname = day["day"]
        levels = day.get("fasting_effective_level", {})
        instant_pot_uses = 0
        day_totals = {p: {"protein": 0.0, "fiber": 0.0, "calories": 0.0} for p in people}
        shakes = {p: 0.0 for p in people}
        day_has_restaurant = {p: False for p in people}
        day_away = {p: bool((day.get("away") or {}).get(p)) for p in people}

        def add_nut(p, nut, sv):
            if p not in day_totals:
                return  # eater outside this (partial) plan
            day_totals[p]["fiber"] += (nut.get("fiber") or 0) * sv
            day_totals[p]["protein"] += (nut.get("protein") or 0) * sv
            day_totals[p]["calories"] += (nut.get("calories") or 0) * sv

        for meal in day.get("meals", []):
            slot = meal["slot"]
            mname = meal.get("name", "?")
            label = f"{dname} {slot} ({mname})"
            src = meal.get("source")
            rid = meal.get("recipe_id")
            rec = recipes.get(rid) if rid is not None else None
            eaters = meal.get("eaters", [])
            servings = meal.get("servings_consumed") or {}

            if rid is not None and rec is None:
                violations.append(f"{label}: recipe_id {rid} not found in recipes.json dump.")
                continue

            # --- Day-of-week rules ---
            if dname in P["no_breakfast_days"] and slot == "Breakfast":
                violations.append(f"{label}: no breakfast may be planned on {dname} (no_breakfast_days).")
            if slot == "Lunch" and dname in P["restaurant_lunch_days"] and src != "restaurant":
                violations.append(f"{label}: {dname} lunch must be a restaurant meal (restaurant_lunch_days).")
            if (slot == "Lunch" and src == "restaurant"
                    and dname not in P["restaurant_lunch_days"] and dname not in rest_lunch_ok):
                violations.append(
                    f"{label}: restaurant lunch on {dname} was not requested (restaurant_lunch_days / "
                    "restaurant_lunch_requested_days)."
                )
            needs_quick = (slot == "Dinner" and dname in quick_days
                           and any(p in P["quick_dinner_people"] for p in eaters))
            if needs_quick and src == "restaurant":
                violations.append(f"{label}: {dname} dinner must be a quick home meal, not a restaurant.")

            # --- Seafood (applies to every source) ---
            if meal.get("contains_seafood"):
                bad = [p for p in eaters if p not in P["seafood_allowed_people"]]
                if bad:
                    violations.append(f"{label}: contains seafood but is served to {', '.join(bad)}.")

            # --- Leftovers: quick by definition; nutrition still counts ---
            if src == "leftovers":
                nut = meal.get("nutrition_per_serving") or {}
                if not nut:
                    warnings.append(f"{label}: leftovers have no nutrition_per_serving; day totals will be low.")
                for p in eaters:
                    add_nut(p, nut, servings.get(p, 1))
                continue

            # --- Restaurant: calories from parameters ---
            if src == "restaurant":
                for p in eaters:
                    if p not in day_totals:
                        continue
                    day_has_restaurant[p] = True
                    rc = person_target(P, p, "restaurant_meal_calories")
                    if rc is None and person_target(P, p, "calories_target"):
                        warnings.append(f"{label}: {p} has a calorie target but no restaurant_meal_calories.")
                    day_totals[p]["calories"] += rc or 0
                continue

            # --- Simple assembly meals ---
            if src == "simple":
                bad = [p for p in eaters if p not in P["simple_assembly_people"]]
                if bad:
                    violations.append(
                        f"{label}: simple assembly meal served to {', '.join(bad)} "
                        "(only simple_assembly_people may have them)."
                    )
                if rec is not None and (rec.get("source") or "") != "Assembly":
                    violations.append(f"{label}: source is simple but recipe {rid} is not an Assembly row.")
                if not meal.get("nutrition_per_serving"):
                    warnings.append(f"{label}: assembly meal has no whole-meal nutrition_per_serving; day totals will be wrong.")
                if not (meal.get("side_ids") or meal.get("new_sides")):
                    warnings.append(f"{label}: assembly meal lists no sides.")

            # --- Sides (any meal: assembly meals and sourced recipes served with plain sides) ---
            if meal.get("side_ids") or meal.get("new_sides"):
                for sid in meal.get("side_ids") or []:
                    srec = recipes.get(sid)
                    if srec is None:
                        violations.append(f"{label}: side id {sid} not found in recipes.json dump.")
                    elif srec.get("category") != "Side":
                        violations.append(f"{label}: side id {sid} ({srec.get('name')}) is not a Side row.")
                    elif srec.get("retired"):
                        violations.append(f"{label}: side {srec.get('name')} is retired.")
                if src != "simple" and not meal.get("nutrition_per_serving"):
                    violations.append(
                        f"{label}: meal has sides but no whole-meal nutrition_per_serving; the recipe's own "
                        "nutrition would leave the sides out of the day totals."
                    )

            # --- Retired ---
            if rec and rec.get("retired"):
                violations.append(f"{label}: recipe is retired.")

            # --- Recency (per person, Monday anchor, inclusive) ---
            if rec and (rec.get("times_used") or 0) >= 1 and not is_exempt(rec):
                for p in eaters:
                    lu = last_used_for(rec, p)
                    if lu and parse_date(lu) >= plan_monday - recency:
                        if meal.get("user_requested"):
                            warnings.append(f"{label}: recency overridden for {p} by explicit user request (last used {lu}).")
                        else:
                            violations.append(
                                f"{label}: {p} last had this {lu}, within {P['recency_days']} days of plan Monday {plan_monday}."
                            )

            # --- Works-for and shared-meal fields ---
            # "No" = this person cannot eat it as written or modified; "Modified" = it needs a
            # stated change for them (substitution or split preparation) that the plan notes must show.
            if rec:
                for p in eaters:
                    wf = rec.get(f"works_for_{p.lower()}")
                    if wf is None or f"works_for_{p.lower()}" not in rec:
                        warnings.append(f"{label}: works_for_{p.lower()} missing from the dump; not checked for {p}.")
                    elif wf == "No":
                        violations.append(f"{label}: recipe is marked works_for_{p.lower()} = No, but {p} is eating it.")
                    elif wf == "Modified":
                        warnings.append(f"{label}: works_for_{p.lower()} = Modified; state {p}'s modification in the plan notes and recipe card.")
                if len(eaters) > 1:
                    sm = rec.get("shared_meal_safe")
                    if sm is None or "shared_meal_safe" not in rec:
                        warnings.append(f"{label}: shared_meal_safe missing from the dump; shared use not checked.")
                    elif sm == "No":
                        violations.append(f"{label}: recipe is marked shared_meal_safe = No but is planned as a shared meal.")
                    elif sm == "Modified":
                        warnings.append(f"{label}: shared_meal_safe = Modified; state the split preparation in the plan notes and recipe card.")

            # --- Ratings ---
            if rec:
                for p in eaters:
                    rating = rec.get(f"rating_{p.lower()}")
                    if bad_rating(rating):
                        violations.append(f"{label}: {p} rated this recipe {rating} (at or below {cutoff}).")

            # --- Fasting compliance ---
            for p in eaters:
                lvl = int(levels.get(p, 0) or 0)
                if lvl <= 0:
                    continue
                if rec and src != "simple":
                    flag = rec.get(f"fasting_lvl_{lvl}")
                else:
                    flag = (meal.get("fasting_flags") or {}).get(str(lvl))
                if flag is None:
                    warnings.append(f"{label}: fasting level {lvl} compliance unknown for {p}.")
                elif not flag:
                    violations.append(f"{label}: not compliant with {p}'s fasting level {lvl}.")

            # --- Flavor variety (solo meals of flavor_variety_people) ---
            if len(eaters) == 1 and eaters[0] in P["flavor_variety_people"] and slot in MAIN_SLOTS:
                p = eaters[0]
                fk = norm_key((rec or {}).get("flavor_key")) or norm_key(meal.get("flavor_key"))
                if fk is None:
                    warnings.append(f"{label}: no flavor_key for {p}'s solo meal; flavor variety unchecked.")
                elif not (rec and is_exempt(rec)):
                    seen = recent_flavor[p].get(fk)
                    if seen:
                        if meal.get("user_requested"):
                            warnings.append(f"{label}: flavor variety overridden for {p} by explicit user request ({fk}, {seen}).")
                        else:
                            violations.append(
                                f"{label}: {p} had '{fk}' in the week of {seen}, within {P['recency_days']} days "
                                "(same protein and flavor profile, regardless of sides or method)."
                            )

            # --- Variety (per person, every main slot; single-day pins excluded) ---
            if meal.get("user_pinned_single_day"):
                if not meal.get("user_requested"):
                    violations.append(
                        f"{label}: user_pinned_single_day is set but user_requested is not; "
                        "only meals the user named can be pinned."
                    )
                for p in eaters:
                    pinned_seen.setdefault((p, slot, mname), []).append(dname)
                warnings.append(f"{label}: user-pinned single-day meal; excluded from variety limits (list it in the plan notes).")
            elif slot in MAIN_SLOTS:
                for p in eaters:
                    if p in variety:
                        variety[p][slot].add(mname)

            # --- New-recipe tracking ---
            if slot in MAIN_SLOTS:
                if src == "new_web":
                    new_recipes.add(mname)
                elif (src != "simple" and rec and (rec.get("times_used") or 0) == 0
                      and rec.get("category") != "Snack"):
                    new_recipes.add(mname)

            # --- Snacks ---
            if slot == "Snack":
                if src == "new_web":
                    if mname not in new_snacks_warned:
                        new_snacks_warned.add(mname)
                        warnings.append(
                            f"{label}: new snack component (not yet in DB); confirm it was user-approved and "
                            "insert it with category 'Snack' in Step 5a."
                        )
                elif src != "database" or rec is None or rec.get("category") != "Snack":
                    violations.append(
                        f"{label}: snack components must be database recipes with category 'Snack', "
                        "or user-approved new components marked source new_web."
                    )
                blocked = recent_snack.get(rid, set()) & set(eaters)
                if blocked and not (rec and is_exempt(rec)):
                    violations.append(
                        f"{label}: snack component eaten by {', '.join(sorted(blocked))} within the last "
                        f"{P['recency_days']} days."
                    )

            # --- Protein shakes ---
            rname = (rec.get("name") if rec else mname) or ""
            if rname.lower() == shake_name:
                for p in eaters:
                    if p in shakes:
                        shakes[p] += servings.get(p, 1)

            # --- Instant Pot ---
            if meal.get("instant_pot"):
                instant_pot_uses += 1
            elif rec and rec.get("primary_appliance") == "Instant Pot":
                warnings.append(f"{label}: DB says primary_appliance is Instant Pot but plan marks instant_pot false. Verify.")

            # --- Egg whole-number scaling ---
            eggs = meal.get("eggs_in_recipe") or 0
            mult = meal.get("multiplier")
            if eggs and mult is not None:
                total = eggs * mult
                if abs(total - round(total)) > EGG_EPSILON:
                    violations.append(f"{label}: {eggs} eggs x multiplier {mult} = {total:.2f}, not a whole number.")

            # --- Quick dinners (simple assembly counts as quick) ---
            if needs_quick and src != "simple":
                if rec is not None:
                    if not rec.get("quick_dinner"):
                        violations.append(f"{label}: quick dinner required on {dname} but quick_dinner is not true.")
                else:
                    rt = meal.get("raw_total_minutes")
                    if rt is None:
                        warnings.append(f"{label}: quick dinner required on {dname}; raw_total_minutes not provided.")
                    elif rt > QUICK_RAW_MAX:
                        violations.append(
                            f"{label}: quick dinner required on {dname} but raw total is {rt} min "
                            f"(> {QUICK_RAW_MAX})."
                        )

            # --- Simple-prep limits for solo meals ---
            if (len(eaters) == 1 and eaters[0] in P["simple_prep_people"]
                    and src not in NON_RECIPE_SOURCES):
                p = eaters[0]
                if rec is not None:
                    prep = raw_minutes(rec, "prep", mult_buf)
                    cook = raw_minutes(rec, "cook", mult_buf)
                    tot = None if prep is None and cook is None else (prep or 0) + (cook or 0)
                else:
                    prep = meal.get("raw_prep_minutes")
                    tot = meal.get("raw_total_minutes")
                packaged_snack = slot == "Snack" and rec is not None and rec.get("category") == "Snack"
                if prep is None or tot is None:
                    if not packaged_snack:
                        warnings.append(f"{label}: {p}'s solo meal is missing raw prep or total time; simple-prep limits unchecked.")
                else:
                    if prep > P["simple_prep_hands_on_max_minutes"]:
                        violations.append(
                            f"{label}: {p}'s solo meal has {prep:.0f} min raw prep "
                            f"(> {P['simple_prep_hands_on_max_minutes']})."
                        )
                    if tot > P["simple_prep_raw_total_max_minutes"]:
                        violations.append(
                            f"{label}: {p}'s solo meal has {tot:.0f} min raw total "
                            f"(> {P['simple_prep_raw_total_max_minutes']})."
                        )

            # --- Nutrition accumulation ---
            nut = meal.get("nutrition_per_serving") or {}
            if rec and not nut and src != "simple":
                nut = {
                    "protein": rec.get("protein_per_serving"),
                    "fiber": rec.get("fiber_per_serving"),
                    "calories": rec.get("calories_per_serving"),
                }
            for p in eaters:
                add_nut(p, nut, servings.get(p, 1))
                # No per-meal fiber cap; only the daily window is checked below.

        day_report.append((dname, {p: dict(day_totals[p]) for p in people},
                           {p: day_has_restaurant[p] for p in people}))

        # --- Per-day checks ---
        if instant_pot_uses > P["instant_pot_max_uses_per_day"]:
            violations.append(
                f"{dname}: Instant Pot used {instant_pot_uses} times (max {P['instant_pot_max_uses_per_day']} per day)."
            )

        for p in people:
            n = shakes[p]
            smax = person_target(P, p, "protein_shakes_max_per_day")
            sdef = person_target(P, p, "protein_shakes_default_per_day")
            if smax is not None and n > smax:
                violations.append(f"{dname}: {p} has {n:g} protein shakes (max {smax}).")
            elif sdef is not None and n > sdef:
                warnings.append(f"{dname}: {p} has {n:g} protein shakes (default {sdef}); call this day out in the plan notes.")

            tot = day_totals[p]
            off_day = day_has_restaurant[p] or day_away[p]
            ct = person_target(P, p, "calories_target")
            if ct:
                tol = person_target(P, p, "calories_tolerance") or 0
                diff = tot["calories"] - ct
                if abs(diff) > tol:
                    msg = f"{dname}: {p} calories {tot['calories']:.0f} vs target {ct} (+/-{tol}); off by {diff:+.0f}."
                    if off_day:
                        warnings.append(msg + " Restaurant/away day: total relies on an assumed value.")
                    else:
                        violations.append(msg)
            soft = person_target(P, p, "protein_soft_min")
            if soft and not off_day and tot["protein"] < soft:
                warnings.append(f"{dname}: {p} protein {tot['protein']:.0f}g below soft goal {soft}g (soft: calories take priority).")
            if day_away[p]:
                warnings.append(
                    f"{dname}: {p} is away for {', '.join(day['away'][p])}; floors not enforced "
                    f"(home totals: {tot['protein']:.0f}g protein, {tot['fiber']:.0f}g fiber)."
                )
                continue
            if day_has_restaurant[p]:
                warnings.append(
                    f"{dname}: {p} has a restaurant meal; floors not enforced "
                    f"(home-cooked totals: {tot['protein']:.0f}g protein, {tot['fiber']:.0f}g fiber)."
                )
                continue
            pmin = person_target(P, p, "protein_min")
            if pmin and tot["protein"] < pmin:
                violations.append(f"{dname}: {p} protein {tot['protein']:.0f}g below minimum {pmin}g.")
            fmin = person_target(P, p, "fiber_min")
            fmax = person_target(P, p, "fiber_max")
            if fmin and tot["fiber"] < fmin:
                violations.append(f"{dname}: {p} fiber {tot['fiber']:.0f}g below minimum {fmin}g.")
            if fmax and tot["fiber"] > fmax:
                violations.append(f"{dname}: {p} fiber {tot['fiber']:.0f}g above maximum {fmax}g.")

    # --- Week-level checks ---
    for (p, slot, mname), days in pinned_seen.items():
        if len(days) > 1:
            violations.append(
                f"Pinned meal '{mname}' ({p}, {slot}) is pinned on {len(days)} days ({', '.join(days)}); "
                "a single-day pin covers one day only, so it counts toward variety."
            )
    for p in people:
        for slot in MAIN_SLOTS:
            limit = variety_limits[slot]
            got = variety[p][slot]
            if len(got) > limit:
                violations.append(
                    f"Variety ({p}): {len(got)} distinct {slot.lower()} recipes ({', '.join(sorted(got))}); max {limit}."
                )
    partial = plan.get("scope", "full") == "partial"
    if partial:
        warnings.append(
            "Partial plan (one person's half): household-wide checks such as the new-recipe minimum, "
            "and limits shared across both halves (Instant Pot per day), are checked on the merged plan."
        )
    elif len(new_recipes) < P["new_recipe_min"]:
        violations.append(
            f"New-recipe minimum: plan has {len(new_recipes)} new recipe(s); at least {P['new_recipe_min']} "
            "breakfast/lunch/dinner recipe must be new from the web or have times_used = 0."
        )

    # --- Report ---
    print("DAY TOTALS (kcal / protein g / fiber g; R = includes a restaurant meal):")
    for dname, tots, rest in day_report:
        parts = [f"{p}: {tots[p]['calories']:.0f} / {tots[p]['protein']:.0f} / {tots[p]['fiber']:.0f}{' R' if rest[p] else ''}"
                 for p in people]
        print(f"  {dname:<9} " + " | ".join(parts))
    print()
    if violations:
        print(f"FAILED: {len(violations)} violation(s)\n")
        for i, v in enumerate(violations, 1):
            print(f"  V{i}. {v}")
    else:
        print("PASSED: no hard-rule violations detected.")
    if warnings:
        print(f"\n{len(warnings)} warning(s) requiring judgment:\n")
        for i, w in enumerate(warnings, 1):
            print(f"  W{i}. {w}")
    print(
        "\nNOT covered by this script: every rule in the household doc without a Script parameter "
        "(check those by hand), recipe similarity, equipment, and ingredients against both profiles."
    )
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
