# -*- coding: utf-8 -*-
"""
Holiday EVENT normalisation -- stop one holiday being counted as several.

WHY THIS MODULE EXISTS
----------------------
The holiday master is a union of several sources, so the same calendar event arrives under
several spellings and, for multi-day holidays, as one row per day. Counting raw NAMES therefore
overstates how much holiday pressure a week is under, which in turn makes a holiday explanation
look stronger than the calendar justifies. Measured on FC_RCA_Holiday_Master_Production.xlsx
(12,197 active rows):

    exact duplicate rows (same country + week + name + date)              1,495
    one name spanning several dates inside ONE fiscal week                  511 buckets
    same country + name + year appearing at two or more DIFFERENT dates      620

An example of each, from the real master:

    exact dupes      Benelux "Ascension Day" 2027-05-06, three identical rows
    multi-day        Bahrain "Eid al-Adha Holiday" on 2025-06-07/08/09/10 -- ONE event, four days
    ambiguous        Indonesia "Ascension of Jesus Christ" 2026-05-14 (source) versus
                     "Ascension Day of Jesus Christ" 2026-05-27..29 (Type "Derived from
                     INPUT_TO_ML", Requires_Review = YES)

A NOTE ON Aggregate_Group -- IT IS NOT AN EVENT FAMILY
-----------------------------------------------------
The Phase 2 brief suggests grouping events by the master's `Aggregate_Group`. The data does not
support that reading: `Aggregate_Group` groups COUNTRIES, not holidays. `AMER_GROUP` contains 64
distinct holiday names across two country labels, and `eCIS` contains 162. Grouping by it would
merge Columbus Day with Thanksgiving Day, and Boxing Day with Bakrid -- inventing exactly the kind
of false equivalence this module exists to prevent. It is left doing its real job, which the
repository already uses it for: resolving an aggregate Country value to member countries
(`holiday_calendar._resolve_country`).

`Semantic_Family` IS an event-family field, but it is populated on only 99 of 12,197 rows (Lunar
New Year, Diwali). It is used where present and cannot be relied on otherwise.

HOW EVENT IDENTITY IS DECIDED
-----------------------------
Conservatively, because a wrong merge is worse than a missed one. Two rows are the same EVENT only
when they share a normalised event key, and the same event INSTANCE only when their dates are
adjacent:

    1. Semantic_Family when the master supplies one.
    2. Otherwise a key built from the name: a MODIFIER prefix plus the significant CORE tokens.

The modifier is what makes this safe. Filler words ("day", "holiday", "of", "the") are dropped so
"Ascension of Jesus Christ" and "Ascension Day of Jesus Christ" reduce to the same core -- but
"Day after Ascension Day" and "Joint Holiday for Waisak Day" carry a modifier (`after`, `joint`)
which is kept in the key, so a bridge day is never merged into the holiday it adjoins. Those are
genuinely different days with genuinely different demand behaviour.

Instances are then grouped by DATE ADJACENCY within a country: consecutive or same dates form one
instance carrying a day count. Two instances of the same event more than a week apart stay
separate and are flagged `possible_misdating` for review rather than merged -- which is the correct
outcome for the Indonesia Ascension case, where the later set is derived data flagged for review,
not a second Ascension.

DEPENDENCIES: standard library only.
"""
import re

# --- words that carry no event identity. Removing them is what collapses the spelling variants. ---
_FILLER = {"day", "days", "holiday", "holidays", "of", "the", "a", "an", "for", "and", "s",
           "public", "national", "federal", "statutory", "official", "gazetted", "restricted",
           "government", "bank", "observance"}

# --- prefixes that make a date a DIFFERENT event from the holiday they reference. Order matters:
#     longer phrases are tested first so "day after" wins over "after". ---
_MODIFIERS = (
    ("joint holiday after", "joint_after"),
    ("joint holiday before", "joint_before"),
    ("joint holiday for", "joint"),
    ("joint holiday", "joint"),
    ("day after", "after"),
    ("day before", "before"),
    ("eve of", "eve"),
    ("observed", "observed"),
    ("substitute", "substitute"),
    ("bridge", "bridge"),
    ("second", "second"),
    ("2nd", "second"),
    ("additional", "additional"),
    ("extra", "extra"),
)

# Two instances of the same event this many days apart or less are the same occurrence spread over
# days; further apart they are separate occurrences (and, within one year, suspicious).
ADJACENCY_DAYS = 1
SAME_OCCURRENCE_DAYS = 7


def _clean(text):
    text = str(text or "").lower().strip()
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9'\s/-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_group_key(v):
    """Normalise a group id the same way `event_key` does, so the two can be compared.

    event_key turns semantic_family "JP_YEAREND" into "family:jp yearend" -- a prefix, lower case,
    and underscores as spaces. Comparing the raw strings therefore never matches, which is exactly
    how the first version of this lookup changed nothing at all.
    """
    t = str(v or "").strip().lower()
    if t.startswith("family:"):
        t = t[len("family:"):]
    return " ".join(t.replace("_", " ").split())


def _group_names():
    """{normalised group key: display name}, resolved lazily so an unstamped master cannot break
    an import. Keys are normalised on the way in, so callers can pass an event_key straight in."""
    global _GROUP_NAMES
    if _GROUP_NAMES is None:
        try:
            from .context_repository import holiday_calendar as _cal
            raw = _cal.semantic_group_names() or {}
        except Exception:
            raw = {}
        _GROUP_NAMES = {_norm_group_key(k): v for k, v in raw.items() if v}
    return _GROUP_NAMES


_GROUP_NAMES = None


def event_key(name, semantic_family=None):
    """A stable identity for a holiday EVENT, independent of spelling.

    Returns (key, modifier, core_tokens). `key` is what to group on. The Semantic_Family from the
    master wins when present, because it is the source's own statement of event identity.
    """
    if semantic_family and str(semantic_family).strip():
        fam = _clean(semantic_family)
        return f"family:{fam}", None, tuple(sorted(set(fam.split())))

    cleaned = _clean(name)
    modifier = None
    for phrase, label in _MODIFIERS:
        if cleaned.startswith(phrase + " ") or cleaned == phrase:
            modifier = label
            cleaned = cleaned[len(phrase):].strip()
            break
        # also catch a trailing form, e.g. "ascension day observed"
        if cleaned.endswith(" " + phrase):
            modifier = label
            cleaned = cleaned[:-len(phrase)].strip()
            break

    tokens = tuple(sorted({t for t in cleaned.split() if t and t not in _FILLER}))
    if not tokens:
        # A name made entirely of filler ("Public Holiday") has no identity of its own; keep the
        # cleaned text so distinct unnamed holidays are not all merged together.
        tokens = tuple(sorted(set(cleaned.split()))) or ("unnamed",)
    key = ("+".join(tokens)) if not modifier else f"{modifier}:{'+'.join(tokens)}"
    return key, modifier, tokens


# prompt2.md clause B: a holiday next to the weekend extends the closure across consecutive days,
# and WHICH side it sits on is a different operational fact. Friday runs the closure forward into
# the weekend; Monday extends it backwards out of one. Lumping both into "adjoining" loses that.
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKEND_WEEKDAYS = ("Saturday", "Sunday")
BEFORE_WEEKEND = "Friday"
AFTER_WEEKEND = "Monday"


def weekday_of(iso):
    """Weekday name for an ISO date string, or None when it cannot be parsed.

    Deliberately tolerant: a malformed date in the master must not take an investigation down.
    """
    try:
        y, m, d = str(iso)[:10].split("-")
        import datetime as _dt
        return WEEKDAY_NAMES[_dt.date(int(y), int(m), int(d)).weekday()]
    except Exception:
        return None


def weekday_structure(dates):
    """Clause B/K: how this event's day(s) sit against the weekend.

    Returns the weekday names plus four independent flags. They are NOT mutually exclusive -- a
    two-day event can straddle Friday and Saturday -- so each is reported on its own rather than
    collapsed into a single pattern label.
    """
    days = [w for w in (weekday_of(d) for d in (dates or [])) if w]
    on_weekend = [w for w in days if w in WEEKEND_WEEKDAYS]
    return {
        "weekdays": days,
        "holiday_on_weekend": bool(on_weekend) and len(on_weekend) == len(days),
        "holiday_touches_weekend": bool(on_weekend),
        # Friday: the closure runs FORWARD into the weekend.
        "holiday_before_weekend": BEFORE_WEEKEND in days,
        # Monday: the closure extends BACKWARD out of the weekend.
        "holiday_after_weekend": AFTER_WEEKEND in days,
        "long_weekend_candidate": bool(on_weekend) or BEFORE_WEEKEND in days or AFTER_WEEKEND in days,
    }


def _date_ordinal(iso):
    """Days since epoch for an ISO date string, or None. Avoids importing datetime for arithmetic
    on a handful of strings, and tolerates the master's mixed formats by only accepting ISO."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    # days-from-civil (Howard Hinnant's algorithm) -- exact, no library, no timezone questions
    y -= mo <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (mo + (-3 if mo > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def normalise(holidays):
    """Collapse a list of holiday dicts into EVENT INSTANCES.

    Input entries are the shape `holiday_calendar` stores: name, type, date, before, after, group,
    needs_review, country, and whatever the caller added (offset_weeks, reaches_target_week...).
    `semantic_family` is used when the caller supplies it.

    Returns a list of instance dicts, each carrying the raw names it absorbed so nothing is lost
    for traceability (spec section 4: "Keep raw source names available").
    """
    grouped = {}
    for h in holidays or []:
        key, modifier, tokens = event_key(h.get("name"), h.get("semantic_family"))
        country = str(h.get("country") or "").strip().lower()
        bucket = grouped.setdefault((country, key), [])
        bucket.append((h, modifier, tokens))

    instances = []
    for (country, key), entries in sorted(grouped.items()):
        # split the bucket into date-adjacent runs -- one run is one occurrence
        dated = sorted(((_date_ordinal(h.get("date")), h, mod) for h, mod, _ in entries),
                       key=lambda t: (t[0] is None, t[0] if t[0] is not None else 0))
        runs = []
        for ordinal, h, mod in dated:
            placed = False
            for run in runs:
                if ordinal is None or run["last"] is None:
                    # undated rows cannot be sequenced; keep them in the first run for this key so
                    # they are not counted as separate occurrences on the strength of a blank
                    if ordinal is None and run["last"] is None:
                        run["rows"].append(h)
                        placed = True
                        break
                    continue
                if abs(ordinal - run["last"]) <= ADJACENCY_DAYS:
                    run["rows"].append(h)
                    run["last"] = max(run["last"], ordinal)
                    run["dates"].add(h.get("date"))
                    placed = True
                    break
            if not placed:
                runs.append({"rows": [h], "first": ordinal, "last": ordinal,
                             "dates": {h.get("date")} if h.get("date") else set(),
                             "modifier": mod})

        for run in runs:
            rows = run["rows"]
            names = sorted({str(r.get("name")) for r in rows})
            dates = sorted({str(r.get("date")) for r in rows if r.get("date")})
            weeks = sorted({r.get("fiscal_week") for r in rows if r.get("fiscal_week") is not None})
            offsets = sorted({r.get("offset_weeks") for r in rows
                              if r.get("offset_weeks") is not None})
            instances.append({
                "event_key": key,
                "country": country,
                "modifier": run.get("modifier"),
                # A stamped semantic group carries a display name written for a reader; use it.
                # names[0] is the alphabetically first RAW spelling, which is right for a family of
                # spelling variants and wrong for one whose members are different words -- Japan's
                # year-end closure was labelled "December 31 Bank Holiday" for a 29 Dec - 3 Jan span.
                "canonical_name": _group_names().get(_norm_group_key(key)) or names[0],
                "raw_names": names,
                "name_variants": len(names),
                "dates": dates,
                # prompt2.md clause D (weekday) and clause B (which side of the weekend). Derived
                # from the DATE, so the weekday belongs to THIS event rather than to the week.
                **weekday_structure(dates),
                "days_in_event": len(dates) or 1,
                "fiscal_weeks": weeks,
                "offset_weeks": offsets,
                "types": sorted({str(r.get("type")) for r in rows if r.get("type")}),
                "needs_review": any(bool(r.get("needs_review")) for r in rows),
                "reaches_target_week": any(bool(r.get("reaches_target_week")) for r in rows)
                if any("reaches_target_week" in r for r in rows) else None,
                "impact_days_before": max((r.get("before") or 0) for r in rows),
                "impact_days_after": max((r.get("after") or 0) for r in rows),
                "source_rows": len(rows),
                "rows_collapsed": len(rows) - 1,
            })

    # Same event, same country, more than one occurrence: distinct instances, but if two
    # occurrences sit inside the same year they may be a mis-dating rather than two holidays.
    # Flagged for review, never merged (spec section 4).
    by_event = {}
    for inst in instances:
        by_event.setdefault((inst["country"], inst["event_key"]), []).append(inst)
    for occurrences in by_event.values():
        if len(occurrences) < 2:
            continue
        for a in occurrences:
            for b in occurrences:
                if a is b or not a["dates"] or not b["dates"]:
                    continue
                oa, ob = _date_ordinal(a["dates"][0]), _date_ordinal(b["dates"][0])
                if oa is None or ob is None:
                    continue
                gap = abs(oa - ob)
                if SAME_OCCURRENCE_DAYS < gap <= 400 and a["dates"][0][:4] == b["dates"][0][:4]:
                    a["possible_misdating"] = True
                    a.setdefault("review_note", (
                        f"The same event appears for {a['country']} at {a['dates'][0]} and "
                        f"{b['dates'][0]} in the same year, {gap} days apart. Kept as separate "
                        f"occurrences; one of them may be mis-dated. Marked for review rather "
                        f"than merged."))
    return instances


def summarise(instances, reaching_only=True):
    """Counts a report can quote without overstating holiday pressure.

    `event_count` is the number of distinct event INSTANCES, which is the number that belongs in a
    narrative. `raw_name_count` is kept beside it so the inflation the normalisation removed stays
    visible and auditable.
    """
    pool = [i for i in instances
            if not reaching_only or i.get("reaches_target_week") in (True, None)]
    raw_names = sorted({n for i in pool for n in i["raw_names"]})
    return {
        "event_count": len(pool),
        "event_keys": sorted({i["event_key"] for i in pool}),
        "canonical_names": sorted({i["canonical_name"] for i in pool}),
        "raw_name_count": len(raw_names),
        "raw_names": raw_names,
        "source_rows": sum(i["source_rows"] for i in pool),
        "rows_collapsed": sum(i["rows_collapsed"] for i in pool),
        "multi_day_events": [i["canonical_name"] for i in pool if i["days_in_event"] > 1],
        "total_holiday_days": sum(i["days_in_event"] for i in pool),
        "needs_review": sorted({i["canonical_name"] for i in pool if i.get("needs_review")}),
        "possible_misdating": sorted({i["canonical_name"] for i in pool
                                      if i.get("possible_misdating")}),
        "note": ("Counted as distinct EVENTS, not as source rows or name spellings: one multi-day "
                 "holiday is one event, and two spellings of the same event on the same date are "
                 "one event. Raw names are retained for traceability."),
    }
