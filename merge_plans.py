#!/usr/bin/env python3
"""Merge two half-plans (split planning) into one full plan for validate_plan.py.

VERSION is printed on every run.

Usage:
    python3 merge_plans.py first_draft.json second_draft.json merged_plan.json
    python3 merge_plans.py encode half.json      # print a half as doc-safe compact JSON

"encode" checks that the file is one JSON object with the keys a saved half needs, then prints it
compact, with <, >, and & written as \u003c, \u003e, \u0026 (still valid JSON; avoids a read
problem in the Claude Doc where those characters split the text).

Exit codes: 0 = merged, 2 = the drafts cannot be merged (nothing written).

Each draft file is one row of the meal_plan_drafts table, as JSON:
{
  "person": "PersonB",
  "plan_json": { ...a plan in validate_plan.py's format with "scope": "partial",
                 "people": ["PersonB"], and only this person's meals... },
  "proposals": [               # first planner only; [] otherwise
    {
      "id": "p1",
      "date": "YYYY-MM-DD",
      "slot": "Dinner",        # Breakfast | Lunch | Snack | Dinner
      "candidates": [          # each candidate is a meal in validate_plan.py's format,
        { ...meal... }         # with "eaters" listing everyone who would eat it and
      ],                       # "servings_consumed" for each of them
      "note": "why these fit both of us"
    }
  ],
  "proposal_decisions": [      # second planner only; [] otherwise
    {"proposal_id": "p1", "decision": "accept", "candidate": 0},
    {"proposal_id": "p2", "decision": "decline"}
  ]
}

Rules:
- Anything both people would eat together (a shared meal, the weekly restaurant dinner, an outing,
  a restaurant lunch) is a proposal from the first planner, with a restaurant meal written as a
  candidate whose source is "restaurant".
- The first planner's plan_json holds a FALLBACK meal for every proposal: a meal for themselves in
  that slot on that date, marked with "proposal_id". Accepting a proposal replaces the fallback with
  the chosen candidate; declining keeps the fallback.
- For an accepted proposal, the second planner's plan_json must have NO meal in that slot on that
  date (the shared meal covers it). For a declined proposal, it must have its own meal there.
- Every proposal needs exactly one decision. Both halves must have the same plan_monday.
- Per-day fields (fasting_effective_level, away) and plan-level request lists are combined.
The output has "scope": "full" and is validated with validate_plan.py like any plan.
"""

import copy
import json
import sys

VERSION = "1.1.0"


class MergeError(Exception):
    pass


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise MergeError(f"Cannot read {path}: {e}")


def merge(first, second):
    a, b = first["plan_json"], second["plan_json"]
    pa, pb = first["person"], second["person"]
    if pa == pb:
        raise MergeError(f"Both drafts are for {pa}.")
    if a.get("plan_monday") != b.get("plan_monday"):
        raise MergeError(f"plan_monday differs: {a.get('plan_monday')} vs {b.get('plan_monday')}.")
    if second.get("proposals"):
        raise MergeError("The second draft has its own proposals; only the first planner proposes.")

    proposals = {p["id"]: p for p in first.get("proposals") or []}
    decisions = {d["proposal_id"]: d for d in second.get("proposal_decisions") or []}
    missing = sorted(set(proposals) - set(decisions))
    extra = sorted(set(decisions) - set(proposals))
    if missing:
        raise MergeError(f"No decision for proposal(s): {', '.join(missing)}.")
    if extra:
        raise MergeError(f"Decision(s) for unknown proposal(s): {', '.join(extra)}.")

    days = {}
    for plan in (a, b):
        for d in plan.get("days", []):
            day = days.setdefault(d["date"], {"date": d["date"], "day": d["day"],
                                               "fasting_effective_level": {}, "meals": []})
            if day["day"] != d["day"]:
                raise MergeError(f"{d['date']} is labeled both {day['day']} and {d['day']}.")
            day["fasting_effective_level"].update(d.get("fasting_effective_level") or {})
            if d.get("away"):
                day.setdefault("away", {}).update(d["away"])

    def meals_for(plan, date):
        return [copy.deepcopy(m) for d in plan.get("days", []) if d["date"] == date for m in d.get("meals", [])]

    report = []
    for date in sorted(days):
        a_meals = meals_for(a, date)
        b_meals = meals_for(b, date)
        merged = []
        for m in a_meals:
            pid = m.get("proposal_id")
            if pid is None:
                merged.append(m)
                continue
            if pid not in proposals:
                raise MergeError(f"{date} meal '{m.get('name')}' points to unknown proposal {pid}.")
            dec = decisions[pid]
            prop = proposals[pid]
            if dec["decision"] == "accept":
                idx = dec.get("candidate", 0)
                try:
                    chosen = copy.deepcopy(prop["candidates"][idx])
                except (IndexError, KeyError):
                    raise MergeError(f"Proposal {pid}: candidate {idx} does not exist.")
                eaters = set(chosen.get("eaters", []))
                if not {pa, pb} <= eaters:
                    raise MergeError(f"Proposal {pid} candidate {idx} does not list both {pa} and {pb} as eaters.")
                clash = [x for x in b_meals if x["slot"] == prop["slot"] and pb in x.get("eaters", [])]
                if clash:
                    raise MergeError(
                        f"Proposal {pid} was accepted, but {pb}'s half still has its own {prop['slot']} on {date} "
                        f"('{clash[0].get('name')}'). Remove it from {pb}'s half."
                    )
                chosen.pop("proposal_id", None)
                merged.append(chosen)
                report.append(f"{date} {prop['slot']}: shared '{chosen.get('name')}' (proposal {pid} accepted)")
            elif dec["decision"] == "decline":
                m.pop("proposal_id", None)
                merged.append(m)
                own = [x for x in b_meals if x["slot"] == prop["slot"] and pb in x.get("eaters", [])]
                if not own:
                    raise MergeError(f"Proposal {pid} was declined, but {pb} has no {prop['slot']} on {date}.")
                report.append(f"{date} {prop['slot']}: {pa} keeps fallback '{m.get('name')}' (proposal {pid} declined)")
            else:
                raise MergeError(f"Proposal {pid}: decision must be accept or decline, not {dec['decision']!r}.")
        merged.extend(b_meals)
        days[date]["meals"] = merged

    unused = set(proposals) - {m.get("proposal_id") for d in a.get("days", []) for m in d.get("meals", [])}
    if unused:
        raise MergeError(f"Proposal(s) with no fallback meal in {pa}'s half: {', '.join(sorted(unused))}.")

    out = {
        "plan_monday": a["plan_monday"],
        "scope": "full",
        "people": sorted({pa, pb}),
        "quick_dinner_requested_days": sorted(set(a.get("quick_dinner_requested_days", [])) |
                                              set(b.get("quick_dinner_requested_days", []))),
        "restaurant_lunch_requested_days": sorted(set(a.get("restaurant_lunch_requested_days", [])) |
                                                  set(b.get("restaurant_lunch_requested_days", []))),
        "days": [days[k] for k in sorted(days)],
    }
    return out, report


HALF_KEYS = ("person", "week_of", "plan_json", "proposals", "proposal_decisions",
             "message_to_other", "pdf_notes", "new_recipe_ids")


def encode(path):
    half = load(path)
    if not isinstance(half, dict):
        raise MergeError("A half must be one JSON object.")
    missing = [k for k in HALF_KEYS if k not in half]
    if missing:
        raise MergeError(f"Half is missing: {', '.join(missing)}.")
    if (half["plan_json"] or {}).get("scope") != "partial":
        raise MergeError('plan_json must have "scope": "partial".')
    s = json.dumps(half, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "encode":
        try:
            print(encode(sys.argv[2]))
        except MergeError as e:
            print(f"CANNOT ENCODE: {e}", file=sys.stderr)
            sys.exit(2)
        return
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    print(f"MERGE v{VERSION}")
    try:
        out, report = merge(load(sys.argv[1]), load(sys.argv[2]))
    except MergeError as e:
        print(f"\nCANNOT MERGE (nothing written):\n{e}")
        sys.exit(2)
    except KeyError as e:
        print(f"\nCANNOT MERGE (nothing written): a draft is missing {e}.")
        sys.exit(2)
    with open(sys.argv[3], "w") as f:
        json.dump(out, f, indent=1)
    print("Merged. Proposal outcomes:")
    for line in report or ["(no proposals)"]:
        print("  " + line)
    print(f"\nWrote {sys.argv[3]}. Validate it with validate_plan.py.")


if __name__ == "__main__":
    main()
