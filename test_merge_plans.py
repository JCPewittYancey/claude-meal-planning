#!/usr/bin/env python3
"""Tests for merge_plans.py. Run: python3 test_merge_plans.py"""
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_validate_plan as TV  # reuses the validator fixtures

MERGE = os.path.join(HERE, "merge_plans.py")


def meal(slot, eaters, name, **kw):
    return TV.meal(slot, eaters, name, **kw)


def first_draft():
    """James plans first: his own meals, one shared-dinner proposal with a fallback."""
    plan = {"plan_monday": "2026-11-16", "scope": "partial", "people": ["James"],
            "days": [{"date": "2026-11-16", "day": "Monday",
                      "fasting_effective_level": {"James": 0},
                      "meals": [
                          meal("Breakfast", ["James"], "Yogurt Bowl", rid=10),
                          meal("Lunch", ["James"], "Fish Lunch (new)", source="new_web", raw_prep_minutes=5,
                               raw_total_minutes=20, contains_seafood=True, flavor_key="tilapia | blackened",
                               nutrition_per_serving={"calories": 450, "protein": 35, "fiber": 10}),
                          meal("Snack", ["James"], "Premier Protein Shake", rid=20),
                          meal("Dinner", ["James"], "Garlic herb salmon", source="simple", contains_seafood=True,
                               flavor_key="salmon | garlic herb", side_ids=[40], proposal_id="p1",
                               nutrition_per_serving={"calories": 640, "protein": 40, "fiber": 10}),
                      ]}]}
    proposals = [{"id": "p1", "date": "2026-11-16", "slot": "Dinner", "note": "fits both",
                  "candidates": [meal("Dinner", ["Jacob", "James"], "Quick Tofu Stir Fry", rid=3,
                                      servings_consumed={"Jacob": 1, "James": 1.3})]}]
    return {"person": "James", "plan_json": plan, "proposals": proposals, "proposal_decisions": []}


def second_draft(decision="accept", own_dinner=False):
    plan = {"plan_monday": "2026-11-16", "scope": "partial", "people": ["Jacob"],
            "days": [{"date": "2026-11-16", "day": "Monday",
                      "fasting_effective_level": {"Jacob": 0},
                      "meals": [
                          meal("Breakfast", ["Jacob"], "Oat Bake", rid=1),
                          meal("Lunch", ["Jacob"], "Bean Bowl", rid=2, servings_consumed={"Jacob": 2}),
                      ]}]}
    if own_dinner:
        plan["days"][0]["meals"].append(meal("Dinner", ["Jacob"], "Quick Tofu Stir Fry", rid=3))
    dec = {"proposal_id": "p1", "decision": decision}
    if decision == "accept":
        dec["candidate"] = 0
    return {"person": "Jacob", "plan_json": plan, "proposals": [], "proposal_decisions": [dec]}


def run_merge(a, b):
    with tempfile.TemporaryDirectory() as d:
        pa, pb, out = (os.path.join(d, n) for n in ("a.json", "b.json", "out.json"))
        json.dump(a, open(pa, "w"))
        json.dump(b, open(pb, "w"))
        r = subprocess.run([sys.executable, MERGE, pa, pb, out], capture_output=True, text=True)
        merged = json.load(open(out)) if os.path.exists(out) else None
        return r.returncode, r.stdout + r.stderr, merged


CASES = []


def case(desc):
    def wrap(fn):
        CASES.append((desc, fn))
        return fn
    return wrap


@case("accepted proposal becomes one shared meal and the fallback is dropped")
def _():
    rc, out, m = run_merge(first_draft(), second_draft("accept"))
    dinners = [x for x in m["days"][0]["meals"] if x["slot"] == "Dinner"]
    return rc == 0 and len(dinners) == 1 and dinners[0]["eaters"] == ["Jacob", "James"] and m["scope"] == "full"


@case("declined proposal keeps the fallback and the second planner's own dinner")
def _():
    rc, out, m = run_merge(first_draft(), second_draft("decline", own_dinner=True))
    names = sorted(x["name"] for x in m["days"][0]["meals"] if x["slot"] == "Dinner")
    return rc == 0 and names == ["Garlic herb salmon", "Quick Tofu Stir Fry"] and \
        all("proposal_id" not in x for x in m["days"][0]["meals"])


@case("accepted proposal with a leftover own dinner in the second half is refused")
def _():
    rc, out, m = run_merge(first_draft(), second_draft("accept", own_dinner=True))
    return rc == 2 and "still has its own Dinner" in out and m is None


@case("declined proposal with no own dinner in the second half is refused")
def _():
    rc, out, m = run_merge(first_draft(), second_draft("decline"))
    return rc == 2 and "has no Dinner" in out


@case("a proposal with no decision is refused")
def _():
    b = second_draft("accept")
    b["proposal_decisions"] = []
    rc, out, m = run_merge(first_draft(), b)
    return rc == 2 and "No decision for proposal" in out


@case("a proposal without a fallback meal is refused")
def _():
    a = first_draft()
    a["plan_json"]["days"][0]["meals"][-1].pop("proposal_id")
    rc, out, m = run_merge(a, second_draft("decline", own_dinner=True))
    return rc == 2 and "no fallback meal" in out


@case("different plan weeks are refused")
def _():
    b = second_draft("accept")
    b["plan_json"]["plan_monday"] = "2026-11-23"
    rc, out, m = run_merge(first_draft(), b)
    return rc == 2 and "plan_monday differs" in out


@case("the merged plan validates as a full plan")
def _():
    rc, out, m = run_merge(first_draft(), second_draft("accept"))
    if rc != 0:
        return False
    vrc, vout = TV.run(m)
    return vrc == 0 and "PASSED" in vout


@case("merge exposes a shared portion not sized to the second person's calorie budget")
def _():
    a = first_draft()
    a["proposals"][0]["candidates"][0]["servings_consumed"]["James"] = 1
    rc, out, m = run_merge(a, second_draft("accept"))
    vrc, vout = TV.run(m)
    return rc == 0 and vrc == 1 and "James calories" in vout


def run_encode(obj):
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "half.json")
        json.dump(obj, open(f, "w"))
        r = subprocess.run([sys.executable, MERGE, "encode", f], capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr


def a_half():
    h = first_draft()
    h.update(week_of="2026-11-16", saved_at="2026-11-15T20:00", message_to_other='a < b & "c" > d',
             pdf_notes=["note"], new_recipe_ids=[])
    return h


@case("encode output round-trips exactly and contains no raw <, >, or &")
def _():
    h = a_half()
    rc, out, err = run_encode(h)
    return rc == 0 and json.loads(out) == h and not any(c in out for c in "<>&")


@case("encode refuses a half missing required keys")
def _():
    h = a_half()
    h.pop("pdf_notes")
    rc, out, err = run_encode(h)
    return rc == 2 and "missing: pdf_notes" in err


@case("encoded halves merge like the originals")
def _():
    rc1, out1, _ = run_encode(a_half())
    b = second_draft("accept")
    b.update(week_of="2026-11-16", saved_at="x", message_to_other=None, pdf_notes=[], new_recipe_ids=[])
    rc2, out2, _ = run_encode(b)
    rc, out, m = run_merge(json.loads(out1), json.loads(out2))
    return rc1 == rc2 == rc == 0 and m["scope"] == "full"


def main():
    failures = 0
    for desc, fn in CASES:
        try:
            ok = fn()
        except Exception as e:  # report, do not crash the suite
            ok = False
            desc += f" (raised {e!r})"
        print(f"{'PASS' if ok else 'FAIL'}  {desc}")
        failures += 0 if ok else 1
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
