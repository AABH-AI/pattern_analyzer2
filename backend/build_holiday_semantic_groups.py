# -*- coding: utf-8 -*-
"""Build the holiday semantic-group tables in Playground, and stamp the runtime JSON from them.

WHAT THIS SOLVES
----------------
`Ascension Day of Jesus Christ` and `Ascension of Jesus Christ` are one holiday written two ways, and
the token-based key already merges those. What it cannot merge is `Qing Ming Festival` /
`Qing Ming Jie`, or `Showa Day` / `Shōwa Day`, or `Diwali` / `Deepavali` -- names that share no
significant token. Measured over this master: after a same-country same-date pre-filter, 276 name
pairs remain and a rule decides only 23% of them.

WHAT IT MUST NOT DO, and the reason this is a curated table rather than a similarity threshold
----------------------------------------------------------------------------------------------
Roughly half the hard pairs are the INVERSE problem -- different holidays that merely share a date:

    Mid-Autumn Festival        + National Day          china, 2023-10-01
    Christmas Day              + Quaid-e-Azam Day      pakistan, 12-25
    Annunciation of the Virgin + Greek Independence Day greece, 03-25

and one pair of near-identical NAMES that are different holidays:

    new year's day   Gregorian, 01-01
    New Year         LUNAR, falls late Jan / Feb in china

Merging any of those corrupts every phase effect downstream, silently. So the mapping is explicit,
each row carries its rationale, and anything not listed keeps its own derived identity. The bias is
stated once and applied throughout: WHEN UNSURE, DO NOT MERGE. Failing to merge inflates an event
count; wrongly merging invents a finding.

TABLES CREATED (Playground)
    dbo.Holiday_Semantic_Group    one row per canonical event family
    dbo.Holiday_Name_Alias        raw name  -> group, with the reason it was mapped
    dbo.Holiday_Name_Pair_Review  same-country same-date pairs NOT resolved here, for review

    python build_holiday_semantic_groups.py            # build + report, writes SQL only
    python build_holiday_semantic_groups.py --stamp    # also stamp holiday_master.json
"""
from __future__ import annotations

import collections
import difflib
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sql_backend import connect, load_config                                   # noqa: E402

STAMP = "--stamp" in sys.argv
JSON_PATH = os.path.join(HERE, "wfm", "context_repository", "holiday_master.json")

# =============================================================================================
# THE MAPPING.  (group_id, display_name, [raw names], rationale)
#
# Scope note: curated for the countries the current test set exercises (china, japan, india) plus
# the cross-country families that recur everywhere. Every other name keeps its derived identity --
# which is the safe default, not an omission.
# =============================================================================================
GROUPS = [
    # ---- CHINA ---------------------------------------------------------------------------------
    ("CN_QINGMING", "Qing Ming Festival",
     ["Qing Ming Festival", "Qing Ming Jie", "Qing Ming Jie holiday"],
     "'Jie' is the Mandarin for festival, so Qing Ming Jie and Qing Ming Festival are the same "
     "event transliterated two ways. Shares no significant token, so no rule could merge them."),

    ("CN_LABOR", "Labor Day (China)",
     ["Labor Day", "Labour Day", "Labor Day Holiday", "Labour Day Holiday"],
     "Labor/Labour is a spelling variant. Scoped to china: 'Labour Day' elsewhere is a different "
     "date entirely -- the master carries it in five different months across countries."),

    ("CN_MIDAUTUMN", "Mid-Autumn Festival",
     ["Mid-Autumn Festival", "Mid-Autumn Festival holiday"],
     "The bare name and its extension day are one family. Deliberately NOT grouped with National "
     "Day even though they coincided on 2023-10-01 -- see the review table."),

    ("CN_NATIONALDAY", "National Day (China)",
     ["National Day", "National Day Golden Week holiday"],
     "Golden Week is the extended break following National Day; one family."),

    ("CN_DRAGONBOAT", "Dragon Boat Festival",
     ["Dragon Boat Festival", "Dragon Boat Festival holiday"], "Bare name plus extension day."),

    ("CAL_LUNARNEWYEAR", "Lunar New Year / Spring Festival",
     # "Lunar New Year" appears BOTH as a raw holiday name and as the master's own pre-existing
     # semantic_family value; listing it here absorbs both into one group instead of leaving the
     # family split across two strings.
     ["New Year", "Lunar New Year", "Spring Festival Eve",
      "Spring Festival Golden Week holiday", "Spring Festival Golden Week Extended Holiday"],
     "Spring Festival IS Lunar New Year. china's bare 'New Year' rows fall late Jan to mid Feb, "
     "which is lunar -- NOT the Gregorian 01-01, which stays separate as CAL_NEWYEAR_GREGORIAN. "
     "This is the most dangerous pair in the master: near-identical names, different holidays."),

    # ---- JAPAN ---------------------------------------------------------------------------------
    ("JP_SHOWA", "Showa Day",
     ["Showa Day", "Shōwa Day"], "Macron variant of one name."),

    ("JP_CHILDRENS", "Children's Day (Japan)",
     ["childrens day", "Children's Day"], "Apostrophe and capitalisation variant."),

    ("JP_MARINE", "Marine Day",
     ["sea ​​day", "sea day", "Marine Day"],
     "The source name carries two ZERO-WIDTH SPACES, so it will not match anything typed by hand. "
     "Recorded here so the join works and the corruption is visible."),

    ("JP_SPRINGEQUINOX", "Spring Equinox",
     ["Spring Equinox", "March Equinox"],
     "Both are the March equinox. Autumn Equinox is a DIFFERENT event in September and is not "
     "included -- an equinox-shaped name is not enough."),

    ("JP_YEAREND", "Year-End / New Year bank holidays (Japan)",
     ["Year-End Holiday", "December 31 Bank Holiday", "January 2 Bank Holiday",
      "January 3 Bank Holiday", "New Year's Holiday"],
     "One extended banking closure spanning the year boundary. Grouped for DISPLAY; the dated "
     "occurrences stay distinct, so a five-day span is still five days and not one."),

    # ---- INDIA ---------------------------------------------------------------------------------
    ("CAL_DIWALI", "Diwali",
     ["Diwali", "Deepavali", "Deepawali", "Divali", "Festival of Lights"],
     "The Diwali/Deepavali case: same festival, no shared token, unreachable by any string rule. "
     "This is the pair that prompted the whole exercise."),

    ("CAL_VESAK", "Buddha Purnima / Vesak",
     ["Buddha Purnima/Vesak", "Buddha Purnima", "Vesak", "Vesak Day", "Waisak Day",
      "Waisak", "Buddha's Birthday"],
     "Vesak / Waisak / Buddha Purnima are one festival across transliterations. Note the master "
     "already ships some slash-combined names, which is the same instinct as this table."),

    # ---- CROSS-COUNTRY families ----------------------------------------------------------------
    ("CAL_NEWYEAR_GREGORIAN", "New Year's Day",
     ["new year's day", "New Year's Day", "New Year Day", "1 January", "Jan 1"],
     "GREGORIAN 01-01 only. Kept apart from CN_LUNARNEWYEAR on purpose; the two are weeks apart "
     "and merging them would fold a February event into January."),

    ("CAL_CHRISTMAS", "Christmas Day",
     ["Christmas", "Christmas Day", "Christmas Holiday"],
     "NOT grouped with Boxing Day / St Stephen's Day / Second Day of Christmas -- those are the "
     "following day and are a separate family below."),

    ("CAL_BOXINGDAY", "Boxing Day / Second Day of Christmas",
     ["Boxing Day", "St.Stephen's Day", "St Stephen's Day", "Second Day of Christmas",
      "2nd Christmas Day"],
     "Four names for 26 December. None shares a token with the others, so this needed a table."),

    ("CAL_ASCENSION", "Ascension of Jesus Christ",
     ["Ascension of Jesus Christ", "Ascension Day of Jesus Christ", "Ascension DAY of Jesus Christ",
      "Ascension Day"],
     # "Prophet's Ascension" was in this list and is NOT this event -- it is Isra and Mi'raj, the
     # Islamic night journey, which falls in Rajab. Both names contain "Ascension", which is why a
     # similarity score would make the same mistake. It now sits in CAL_ISRA.
     "Note: the two Ascension rows for indonesia sit on DIFFERENT dates (05-14 and 05-27) and both "
     "carry needs_review. Grouping them names the family; it does not merge the occurrences, and "
     "the double-dating remains a source defect to fix upstream."),

    ("CAL_LABOURDAY_MAY", "International Workers' Day (1 May)",
     ["International Worker's Day", "International Workers' Day", "May Day", "May 1st",
      "Labor Day / May Day", "International Labor Day", "Day off for International Workers' Day"],
     "The 1 May observance. Deliberately EXCLUDES the September Labor Day of canada and the USA, "
     "and china's own Labor Day, which has its own group."),

    ("CAL_ASHURA", "Ashura",
     ["Ashura", "Ashoora", "Muharram/Ashura"], "Transliteration variants."),

    ("CAL_ISLAMICNEWYEAR", "Islamic New Year",
     ["Islamic New Year", "Muharram", "Al-Hijra (Islamic New Year)", "Al-Hijra"],
     "Muharram 1 is the Islamic new year. Muharram/Ashura is a combined name and belongs to "
     "CAL_ASHURA, since Ashura is the 10th of Muharram, not the 1st."),

    ("CAL_MAWLID", "Prophet's Birthday",
     ["Mouloud", "Prophet Mohamed's Birthday", "The Prophet's Birthday", "Mawlid",
      "Milad un-Nabi/Id-e-Milad", "Milad un-Nabi"], "Transliteration variants of Mawlid."),

    ("CAL_ARAFAT", "Day of Arafah",
     ["Arafah", "Arafat Day", "Waqfat Arafat Day", "Day of Arafah"],
     "One day, four spellings. NOT grouped with Eid al-Adha Eve -- see the review table; the two "
     "coincide but a vigil and a festival eve are not self-evidently one event."),

    ("CAL_ISRA", "Isra and Mi'raj",
     ["Isra and Miraj", "Isra and Mi'raj", "Isra and Mi`raj", "Prophet's Ascension",
      "Prophet Ascension", "Lailat al-Miraj"],
     "Apostrophe variants, plus \"Prophet's Ascension\" -- the same event named by what it is "
     "rather than transliterated. It must NOT go to CAL_ASCENSION: that is the Christian Ascension "
     "in May, this is Rajab. The shared word 'Ascension' is a trap, not a signal."),
]

# Pairs deliberately NOT merged, recorded so the decision is visible and reversible.
# Country-scoped aliases: a name whose identity depends on WHERE it is observed. The alias table
# carries `country_scope` for exactly this, so a scoped row resolves the local case without touching
# the same name elsewhere.
SCOPED_ALIASES = [
    ("Labor Day", "nordics", "CAL_LABOURDAY_MAY",
     "In the Nordics Labour Day is 1 May, so bare 'Labor Day' and 'May Day' are one event there. "
     "Left global-unmapped on purpose: in canada and the USA it is September."),
    ("Labour Day", "nordics", "CAL_LABOURDAY_MAY", "As above."),
    ("Labor Day", "ecis", "CAL_LABOURDAY_MAY", "1 May observance in the eCIS countries."),
    ("Labour Day", "ecis", "CAL_LABOURDAY_MAY", "As above."),
    ("Labor Day", "ecis_1", "CAL_LABOURDAY_MAY", "As above."),
    ("Labour Day", "ecis_1", "CAL_LABOURDAY_MAY", "As above."),
]

DO_NOT_MERGE = [
    ("Mid-Autumn Festival", "National Day", "china",
     "Coincided on 2023-10-01. A lunar harvest festival and the PRC founding anniversary are "
     "different events that happened to fall together."),
    ("new year's day", "New Year", "china",
     "Near-identical NAMES, different holidays: Gregorian 01-01 versus lunar New Year in Feb."),
    ("Christmas Day", "Quaid-e-Azam Day", "pakistan",
     "Both 12-25. Jinnah's birthday is not Christmas."),
    ("Annunciation of the Virgin Mary", "Greek Independence Day", "greece",
     "Both 03-25 and both real."),
    ("Qing Ming Festival", "childrens day", "taiwan",
     "Both 04-04. Tomb-sweeping and children's day are unrelated."),
    ("Spring Equinox", "Autumn Equinox", None,
     "Opposite ends of the year. An equinox-shaped name is not an event identity."),
    ("Arafah", "Eid al-Adha Eve", None,
     "They coincide, but a vigil day and a festival eve are not self-evidently the same event. "
     "Left for a business decision rather than assumed."),
    ("Mountain Day", "Day off for Mountain Day", None,
     "A bridge day is already handled by the modifier prefix in the derived key and must stay "
     "distinguishable from its anchor."),
]

DDL = """
IF OBJECT_ID('dbo.Holiday_Semantic_Group','U') IS NOT NULL DROP TABLE dbo.Holiday_Semantic_Group;
CREATE TABLE dbo.Holiday_Semantic_Group (
    group_id      varchar(40)   NOT NULL PRIMARY KEY,
    display_name  nvarchar(200) NOT NULL,
    rationale     nvarchar(1000)    NULL,
    name_count    int               NULL,
    created_at    datetime      NOT NULL DEFAULT GETDATE()
);

IF OBJECT_ID('dbo.Holiday_Name_Alias','U') IS NOT NULL DROP TABLE dbo.Holiday_Name_Alias;
CREATE TABLE dbo.Holiday_Name_Alias (
    raw_name      nvarchar(200) NOT NULL,
    country_scope varchar(40)       NULL,   -- NULL = applies to every country
    group_id      varchar(40)   NOT NULL,
    master_rows   int               NULL,   -- how many Holiday_Master rows this name matches
    created_at    datetime      NOT NULL DEFAULT GETDATE()
);
CREATE INDEX IX_Holiday_Name_Alias_name ON dbo.Holiday_Name_Alias (raw_name);

IF OBJECT_ID('dbo.Holiday_Name_Pair_Review','U') IS NOT NULL DROP TABLE dbo.Holiday_Name_Pair_Review;
CREATE TABLE dbo.Holiday_Name_Pair_Review (
    name_a        nvarchar(200) NOT NULL,
    name_b        nvarchar(200) NOT NULL,
    country_scope varchar(40)       NULL,
    slots         int               NULL,   -- country-dates where both names appear
    verdict       varchar(20)   NOT NULL,   -- DO_NOT_MERGE | UNRESOLVED
    rationale     nvarchar(1000)    NULL,
    created_at    datetime      NOT NULL DEFAULT GETDATE()
);
"""


def main():
    cfg = load_config()
    cn = connect(cfg)
    cu = cn.cursor()

    print("=" * 108)
    print("BUILDING HOLIDAY SEMANTIC GROUPS in Playground")
    print("=" * 108)

    for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
        cu.execute(stmt)
    cn.commit()
    print("\n  3 table(s) created")

    # How many master rows each raw name actually matches -- a mapping nothing matches is noise.
    cu.execute("SELECT holiday_name, country_key, COUNT(*) FROM dbo.Holiday_Master "
               "GROUP BY holiday_name, country_key")
    counts = collections.Counter()
    for name, country, n in cu.fetchall():
        counts[(str(name).strip().lower(), str(country).strip().lower())] += n
    by_name = collections.Counter()
    for (nm, _c), n in counts.items():
        by_name[nm] += n

    matched = unmatched = 0
    for gid, display, names, why in GROUPS:
        cu.execute("INSERT INTO dbo.Holiday_Semantic_Group (group_id, display_name, rationale, "
                   "name_count) VALUES (?,?,?,?)", gid, display, why, len(names))
        scope = None
        low = gid.split("_")[0].lower()
        if low in ("cn",):
            scope = "china"
        elif low in ("jp",):
            scope = "japan"
        elif low in ("in",):
            scope = "india"
        for nm in names:
            hits = by_name.get(nm.strip().lower(), 0)
            matched += 1 if hits else 0
            unmatched += 0 if hits else 1
            cu.execute("INSERT INTO dbo.Holiday_Name_Alias (raw_name, country_scope, group_id, "
                       "master_rows) VALUES (?,?,?,?)", nm, scope, gid, hits)
    for nm, scope, gid, why in SCOPED_ALIASES:
        hits = counts.get((nm.strip().lower(), scope.strip().lower()), 0)
        matched += 1 if hits else 0
        unmatched += 0 if hits else 1
        cu.execute("INSERT INTO dbo.Holiday_Name_Alias (raw_name, country_scope, group_id, "
                   "master_rows) VALUES (?,?,?,?)", nm, scope, gid, hits)
    cn.commit()
    print("  %d group(s), %d alias row(s)  (%d match the master, %d are forward-looking spellings)"
          % (len(GROUPS), matched + unmatched, matched, unmatched))

    for a, b, scope, why in DO_NOT_MERGE:
        cu.execute("INSERT INTO dbo.Holiday_Name_Pair_Review (name_a, name_b, country_scope, "
                   "slots, verdict, rationale) VALUES (?,?,?,?,?,?)",
                   a, b, scope, None, "DO_NOT_MERGE", why)
    cn.commit()
    print("  %d DO_NOT_MERGE decision(s) recorded" % len(DO_NOT_MERGE))

    # Everything still unresolved: same country, same date, and neither rule nor table settles it.
    cu.execute("SELECT country_key, holiday_date, holiday_name FROM dbo.Holiday_Master "
               "WHERE holiday_name IS NOT NULL AND LTRIM(RTRIM(holiday_name)) <> ''")
    slots = collections.defaultdict(set)
    for c, d, n in cu.fetchall():
        slots[(str(c), str(d)[:10])].add(str(n).strip())

    cu.execute("SELECT LOWER(raw_name), group_id FROM dbo.Holiday_Name_Alias")
    alias = {r[0]: r[1] for r in cu.fetchall()}
    decided = {(a.lower(), b.lower()) for a, b, _s, _w in DO_NOT_MERGE}
    decided |= {(b, a) for a, b in decided}

    STOP = {"day", "holiday", "of", "the", "and", "for", "off", "in", "on", "public", "national",
            "observed", "substitute", "bridge", "joint", "eve", "st", "saint", "s"}

    def toks(n):
        t = re.sub(r"[^a-z0-9 ]+", " ", n.lower())
        return {w for w in t.split() if w and w not in STOP and len(w) > 2}

    unresolved = collections.defaultdict(list)
    for (country, date), names in slots.items():
        ns = sorted(names)
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                a, b = ns[i], ns[j]
                ga, gb = alias.get(a.lower()), alias.get(b.lower())
                if ga and gb and ga == gb:
                    continue                                    # table merged them
                if (a.lower(), b.lower()) in decided:
                    continue                                    # table split them
                if toks(a) & toks(b):
                    continue                                    # a rule can decide it
                if difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.86:
                    continue
                unresolved[(a, b)].append((country, date))

    for (a, b), where in unresolved.items():
        cu.execute("INSERT INTO dbo.Holiday_Name_Pair_Review (name_a, name_b, country_scope, "
                   "slots, verdict, rationale) VALUES (?,?,?,?,?,?)",
                   a, b, where[0][0], len(where), "UNRESOLVED",
                   "co-occurs on %d country-date slot(s); neither a rule nor the alias table "
                   "settles it. Needs a business decision: one event or two?" % len(where))
    cn.commit()
    print("  %d pair(s) still UNRESOLVED and queued for review" % len(unresolved))

    print("\n" + "=" * 108)
    print("WHAT THE TABLE NOW RESOLVES")
    print("=" * 108)
    cu.execute("""
        SELECT g.group_id, g.display_name, COUNT(DISTINCT a.raw_name), SUM(ISNULL(a.master_rows,0))
        FROM dbo.Holiday_Semantic_Group g
        LEFT JOIN dbo.Holiday_Name_Alias a ON a.group_id = g.group_id
        GROUP BY g.group_id, g.display_name
        HAVING SUM(ISNULL(a.master_rows,0)) > 0
        ORDER BY SUM(ISNULL(a.master_rows,0)) DESC
    """)
    print("\n  %-24s %-42s %7s %9s" % ("GROUP", "DISPLAY NAME", "NAMES", "ROWS"))
    print("  " + "-" * 88)
    for r in cu.fetchall():
        print("  %-24s %-42s %7s %9s" % (r[0], str(r[1])[:42], r[2], r[3]))

    if STAMP:
        stamp_json(cu)
    else:
        print("\n  (JSON not stamped -- re-run with --stamp to write semantic_family into "
              "holiday_master.json)")
    cn.close()


def stamp_json(cu):
    """Write the group ids into the runtime JSON's `semantic_family`, which the engine already
    prefers over its derived key. The engine therefore needs no code change."""
    d = json.load(io.open(JSON_PATH, encoding="utf-8"))
    cu.execute("SELECT LOWER(raw_name), country_scope, group_id FROM dbo.Holiday_Name_Alias")
    generic, scoped = {}, {}
    for nm, scope, gid in cu.fetchall():
        (scoped.setdefault(str(scope).lower(), {}) if scope else generic)[nm] = gid

    stamped = kept = 0

    def walk(node, country=None):
        nonlocal stamped, kept
        if isinstance(node, dict):
            if "name" in node and "date" in node:
                nm = str(node.get("name") or "").strip().lower()
                # Country-scoped first, then the cross-country families. Scoping is load-bearing:
                # "Labor Day" in china is the 1 May observance, in canada it is September.
                gid = (scoped.get(str(country or "").lower(), {}).get(nm)) or generic.get(nm)
                # A row that ALREADY carried a semantic_family keeps its family, translated to the
                # new id where the table knows it. Without this the master's own "Lunar New Year"
                # and this table's CAL_LUNARNEWYEAR would be two groups for one festival.
                if not gid:
                    prior = str(node.get("semantic_family") or "").strip()
                    if prior:
                        gid = generic.get(prior.lower()) or prior
                if gid:
                    node["semantic_family"] = gid
                    stamped += 1
                else:
                    kept += 1
                return
            for k, v in node.items():
                walk(v, k, )
        elif isinstance(node, list):
            for v in node:
                walk(v, country)

    # The JSON keys holidays as "country|fiscal_week", so the country has to be split out of the
    # composite key. Passing the whole key made every country-scoped mapping miss silently.
    for composite, rows in (d.get("holidays") or {}).items():
        ckey = str(composite).split("|")[0].strip().lower()
        walk(rows, ckey)
    # The DISPLAY name for each group travels with the stamps. Without it the engine has a group
    # id and no words for it, and falls back to the first raw name in the family -- which labelled
    # a five-day Japanese year-end closure "December 31 Bank Holiday".
    cu.execute("SELECT group_id, display_name FROM dbo.Holiday_Semantic_Group")
    d["semantic_groups"] = {r[0]: r[1] for r in cu.fetchall()}
    d["semantic_group_source"] = "dbo.Holiday_Name_Alias"
    io.open(JSON_PATH, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
    print("\n  stamped holiday_master.json: %d row(s) given a semantic_family, %d left to their "
          "derived key" % (stamped, kept))


if __name__ == "__main__":
    main()
