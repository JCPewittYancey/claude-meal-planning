#!/usr/bin/env python3
"""Deterministic validator for weekly meal plans.

VERSION is printed on every run so the plan session can report which copy ran.

Usage:
    python3 validate_plan.py params.json plan.json recipes.json [snack_history.json]

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

Rules: every key in SCRIPT_SCHEMA must be present and marked Script; a Script
row whose key this script does not know is an error (the doc is ahead of the
code); a known key marked Claude is an error. Claude rows are otherwise ignored.
Values: integers, decimals, comma-separated lists, or "none".

------------------------------------------------------------------------------
plan.json: the draft plan.
{
  "plan_monday": "YYYY-MM-DD",
  "people": ["Jacob", "James"],
  "quick_dinner_requested_days": [],     # one-off quick days for THIS plan only.
                                         # default_quick_dinner_days come from params.
  "restaurant_lunch_requested_days": [], # one-off restaurant lunches the user asked for
  "days": [
    {
      "date": "YYYY-MM-DD",
      "day": "Monday",
      "away": {"James": ["Breakfast", "Lunch", "Snack"]},   # optional: meals missed out of town;
                                                            # that person's floors are not enforced that day
      "fasting_effective_level": {"Jacob": 0, "James": 3},  # 0 = no fast. Apply the olive-oil
            # exception BEFORE writing this (actual 4 or 5 -> 3). Wine on true level 5 is NOT
            # captured here; check by hand.
      "meals": [
        {
          "slot": "Dinner",                  # Breakfast | Lunch | Snack | Dinner
          "eaters": ["James"],
          "recipe_id": 12,                   # null for new_web / restaurant / simple / leftovers
          "name": "Air Fryer Rockfish",
          "source": "database",              # database | new_web | restaurant | simple | leftovers
          "servings_consumed": {"James": 1},
          "multiplier": 0.5,                 # scaling vs base yield; null if n/a
          "eggs_in_recipe": 0,               # eggs in BASE recipe; null/0 if none
          "instant_pot": false,              # true if prep uses the Instant Pot that day (incl. rice)
          "contains_seafood": true,          # REQUIRED true on any meal with fish, shellfish, or a
                                             # seafood-derived ingredient (fish sauce, anchovy, ...)
          "fasting_flags": {"1": true, "2": true, "3": false},
                                             # REQUIRED for new_web and simple meals on fasting days;
                                             # database recipes use their DB flags
          "raw_prep_minutes": 8,             # new_web only: raw hands-on prep (needed for simple-prep)
          "raw_total_minutes": 25,           # new_web only: raw total (quick dinner, simple-prep)
          "nutrition_per_serving": {"calories": 320, "protein": 30, "fiber": 6},
                                             # new_web, simple, leftovers. Restaurant calories come
                                             # from the <person>_restaurant_meal_calories parameter.
          "nutrition_estimated": false,
          "user_requested": false            # true only if the user asked for this recipe this week;
                                             # overrides recency (reported as a warning)
        }
      ]
    }
  ]
}

------------------------------------------------------------------------------
recipes.json: rows for every recipe_id in the plan, joined to the per-person view:
  SELECT r.id, r.name, r.category, r.last_used, v.last_used_jacob, v.last_used_james,
         r.times_used, r.rating_jacob, r.rating_james, r.retired, r.notes,
         r.batch_cook_or_fresh, r.primary_appliance, r.quick_dinner,
         r.prep_time_minutes, r.cook_time_minutes,
         r.prep_time_minutes_raw, r.cook_time_minutes_raw,
         r.protein_per_serving, r.fiber_per_serving, r.calories_per_serving,
         r.fasting_lvl_1, r.fasting_lvl_2, r.fasting_lvl_3, r.fasting_lvl_4, r.fasting_lvl_5
  FROM recipes r JOIN recipe_last_used_by_person v ON v.recipe_id = r.id
  WHERE r.id IN (...all recipe_ids in the plan...);

snack_history.json (required when the plan has snacks):
  SELECT recipe_id, week_of, person FROM meal_plan_history
  WHERE meal_slot = 'Snack' AND week_of >= '[plan_monday minus recency_days]';
"""

import json
import sys
from datetime import date, timedelta

VERSION = "2.0.0"

KNOWN_PEOPLE = ("Jacob", "James")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAIN_SLOTS = ("Breakfast", "Lunch", "Dinner")
NON_RECIPE_SOURCES = ("restaurant", "simple", "leftovers")
EGG_EPSILON = 0.001

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
    "quick_dinner_raw_max_minutes": "int",
    "time_buffer_multiplier": "float",
    "instant_pot_max_uses_per_day": "int",
    "seafood_allowed_people": "people",
    "simple_assembly_people": "people",
    "simple_prep_people": "people",
    "simple_prep_hands_on_max_minutes": "int",
    "simple_prep_raw_total_max_minutes": "int",
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
for _p in KNOWN_PEOPLE:
    for _k, _t in PERSON_KEYS.items():
        SCRIPT_SCHEMA[f"{_p.lower()}_{_k}"] = _t


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
        if by == "script" and key not in SCRIPT_SCHEMA:
            errors.append(
                f"Parameter {key} is marked Script but this validator (v{VERSION}) does not know it. "
                "The validator must be updated before this row can be used."
            )
        if key in SCRIPT_SCHEMA and by != "script":
            errors.append(f"Parameter {key} is read by the validator but is marked {by or 'blank'}, not Script.")
    params = {}
    for key, typ in SCRIPT_SCHEMA.items():
        if key not in seen:
            errors.append(f"Parameter {key} is missing from the doc's Parameters table.")
            continue
        try:
            params[key] = parse_value(key, typ, seen[key][0])
        except InputError as e:
            errors.append(str(e))
    if errors:
        raise InputError("\n".join(errors))
    return params


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
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    print(f"VALIDATOR v{VERSION}")
    try:
        P = load_params(sys.argv[1])
        plan = load(sys.argv[2])
        recipes = {r["id"]: r for r in load(sys.argv[3])}
        snack_history = load(sys.argv[4]) if len(sys.argv) > 4 else []
        people = plan["people"]
        for p in people:
            if p not in KNOWN_PEOPLE:
                raise InputError(f"plan.people contains unknown person {p!r}.")
        plan_monday = parse_date(plan["plan_monday"])
    except InputError as e:
        print("\nINPUT ERROR (nothing was validated):\n")
        print(e)
        sys.exit(2)
    except KeyError as e:
        print(f"\nINPUT ERROR (nothing was validated): plan.json is missing {e}.")
        sys.exit(2)

    print("PARAMETERS USED:")
    for k in SCRIPT_SCHEMA:
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

            if src == "database" and rec is None:
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
            if slot == "Dinner" and src == "restaurant" and dname in quick_days:
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
                if not meal.get("nutrition_per_serving"):
                    warnings.append(f"{label}: simple assembly meal has no nutrition_per_serving.")

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
                if lvl > 3:
                    warnings.append(
                        f"{label}: effective level {lvl} passed for {p}; the olive-oil exception should cap "
                        f"effective levels at 3. Checking fasting_lvl_{lvl} as given."
                    )
                flag = rec.get(f"fasting_lvl_{lvl}") if rec else (meal.get("fasting_flags") or {}).get(str(lvl))
                if flag is None:
                    warnings.append(f"{label}: fasting level {lvl} compliance unknown for {p}.")
                elif not flag:
                    violations.append(f"{label}: not compliant with {p}'s fasting level {lvl}.")

            # --- Variety (per person, every main slot) ---
            if slot in MAIN_SLOTS:
                for p in eaters:
                    variety[p][slot].add(mname)

            # --- New-recipe tracking ---
            if slot in MAIN_SLOTS:
                if src == "new_web":
                    new_recipes.add(mname)
                elif rec and (rec.get("times_used") or 0) == 0 and rec.get("category") != "Snack":
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
            if slot == "Dinner" and dname in quick_days and src != "simple":
                if rec is not None:
                    if not rec.get("quick_dinner"):
                        violations.append(f"{label}: quick dinner required on {dname} but quick_dinner is not true.")
                else:
                    rt = meal.get("raw_total_minutes")
                    if rt is None:
                        warnings.append(f"{label}: quick dinner required on {dname}; raw_total_minutes not provided.")
                    elif rt > P["quick_dinner_raw_max_minutes"]:
                        violations.append(
                            f"{label}: quick dinner required on {dname} but raw total is {rt} min "
                            f"(> {P['quick_dinner_raw_max_minutes']})."
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
            if rec and not nut:
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
    for p in people:
        for slot in MAIN_SLOTS:
            limit = variety_limits[slot]
            got = variety[p][slot]
            if len(got) > limit:
                violations.append(
                    f"Variety ({p}): {len(got)} distinct {slot.lower()} recipes ({', '.join(sorted(got))}); max {limit}."
                )
    if len(new_recipes) < P["new_recipe_min"]:
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
        "\nNOT covered by this script (manual checks): similarity to recently used recipes, "
        "equipment, disliked ingredients (including James's tuna/oyster/clam exclusions), "
        "seafood not flagged with contains_seafood, wine on true level 5 days, perishable "
        "scheduling, lunch-base rotation, breakfast/lunch cooking-session time limits, "
        "overnight-oats travel conflicts, outing scheduling, and eating-out fasting rules "
        "other than the ones above."
    )
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
