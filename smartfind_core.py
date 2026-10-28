"""
SmartFind core logic (REASON + ACT decisions). Pure Python — no Streamlit —
so it can be tested with:  python -m unittest -v

The score is a RULE-BASED SIMILARITY SCORE out of 100 comparing report details.
It is NOT a probability and NOT proof that an item belongs to anyone.
"""
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

MATCH_THRESHOLD = 40   # minimum score listed on the Possible Matches page
NOTIFY_THRESHOLD = 75  # minimum score that creates a (simulated, in-app) notification
CUSTODY_HOLDERS = ("Finder", "OSA")

# ------------------------------------------------------------------
# Campus areas. EXAMPLES ONLY — edit to match your campus.
# Two different location texts earn partial points only if they fall in the
# same area below (or are rooms in the same building, see compare_locations).
# ------------------------------------------------------------------
LOCATION_AREAS = {
    "Library":       ["library"],
    "Laboratory":    ["laboratory", "lab", "computer lab", "comlab"],
    "Canteen":       ["canteen", "cafeteria"],
    "Gymnasium":     ["gym", "gymnasium"],
    "Study Hall":    ["study hall", "study area"],
    "Registrar":     ["registrar"],
}

_FILLER_WORDS = {"room", "rm", "the", "at", "in", "near", "sa", "may", "po", "ng"}
_LOCATION_KEYWORD_STOP_WORDS = {
    "area", "building", "campus", "floor", "entrance", "gate", "hall", "wing",
    "seen", "saw", "found", "nakita",
}
# Room code like "Q-5312" / "Q5312": building letters + 3-4 digits.
# ASSUMPTION: the FIRST digit is the floor (Q-5312 = building Q, 5th floor).
_ROOM_RE = re.compile(r"\b([a-z]{1,3})\s+(\d{3,4})\b")


def normalize_location(text):
    """Lower-case, strip accents/punctuation/filler words, recognise room codes and campus areas."""
    t = unicodedata.normalize("NFKD", str(text or "")).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    t = " ".join(w for w in t.split() if w not in _FILLER_WORDS)
    room = None
    m = _ROOM_RE.search(t)
    if m:
        room = (m.group(1), m.group(2))
        if m.span() == (0, len(t)):
            t = m.group(1) + m.group(2)      # "q 5312" and "q5312" become the same text
    area = None
    for name, aliases in LOCATION_AREAS.items():
        if any(re.search(rf"\b{re.escape(a)}\b", t) for a in aliases):
            area = name
            break
    return {"text": t, "room": room, "area": area}


def compare_locations(a, b):
    """Return (points, detail, result_label, state). Max 20 points."""
    na, nb = normalize_location(a), normalize_location(b)
    if not na["text"] or not nb["text"]:
        return 0, "Location not provided in one report", "Unverified", "unverified"
    if na["text"] == nb["text"]:
        return 20, "Same campus room/area", "Match", "match"
    if na["room"] and nb["room"]:
        if na["room"] == nb["room"]:
            return 20, "Same campus room/area", "Match", "match"
        if na["room"][0] == nb["room"][0]:
            if na["room"][1][0] == nb["room"][1][0]:
                return 12, "Same building and floor", "Partial", "partial"
            return 8, "Same building, different floor", "Partial", "partial"
        return 0, "Different building", "Differs", "differ"
    if na["area"] and na["area"] == nb["area"]:
        return 12, f"Same campus area ({na['area']})", "Partial", "partial"
    if na["area"] and nb["area"] and na["area"] != nb["area"]:
        return 0, "Different location", "Differs", "differ"

    keywords_a = {
        word for word in na["text"].split()
        if len(word) >= 4 and not word.isdigit() and word not in _LOCATION_KEYWORD_STOP_WORDS
    }
    keywords_b = {
        word for word in nb["text"].split()
        if len(word) >= 4 and not word.isdigit() and word not in _LOCATION_KEYWORD_STOP_WORDS
    }
    if keywords_a & keywords_b:
        return 12, "Same location keyword", "Partial", "partial"

    for word_a in keywords_a:
        for word_b in keywords_b:
            shorter, longer = sorted((word_a, word_b), key=len)
            prefix_match = (
                len(shorter) >= 5
                and longer.startswith(shorter)
                and len(shorter) / len(longer) >= 0.45
            )
            close_spelling = (
                len(shorter) >= 6
                and abs(len(word_a) - len(word_b)) <= 2
                and SequenceMatcher(None, word_a, word_b).ratio() >= 0.82
            )
            if prefix_match or close_spelling:
                return 8, "Close location keyword", "Partial", "partial"
    return 0, "Different location", "Differs", "differ"


def calculate_match_score(lost, found):
    """Similarity score out of 100.
    Category 35, Color 20, Location 20, Date 15, Description 10.
    When either report has a brand, description and brand share those 10 points
    (5 each), so brand is supporting evidence without inflating the total."""
    score, rows = 0, []

    def add(rule, detail, result, pts, state):
        nonlocal score
        score += pts
        rows.append({"rule": rule, "detail": detail, "result": result, "pts": pts, "state": state})

    # Category (35)
    c1, c2 = lost["category"].lower().strip(), found["category"].lower().strip()
    if c1 == c2 and c1 != "other":
        add("Category", "Same category", "Match", 35, "match")
    elif c1 == c2:
        add("Category", "Both are 'Other' (not specific)", "Partial", 10, "partial")
    else:
        add("Category", "Different category", "Differs", 0, "differ")

    # Color (20)
    k1, k2 = lost["color"].lower().strip(), found["color"].lower().strip()
    if not k1 or not k2:
        add("Color", "Color not provided in one report", "Unverified", 0, "unverified")
    elif k1 == k2:
        add("Color", "Same color", "Match", 20, "match")
    elif set(k1.split()) & set(k2.split()):          # shared whole word, e.g. "Navy Blue" / "Blue"
        add("Color", "Partly the same color", "Partial", 10, "partial")
    else:
        add("Color", "Different color", "Differs", 0, "differ")

    # Location (20)
    pts, detail, result, state = compare_locations(lost["location"], found["location"])
    add("Location", detail, result, pts, state)

    # Date (15)
    try:
        diff = abs((datetime.strptime(found["date"], "%Y-%m-%d") - datetime.strptime(lost["date"], "%Y-%m-%d")).days)
        if diff == 0:
            add("Date", "Same day", "Match", 15, "match")
        elif diff <= 2:
            add("Date", f"{diff} day(s) apart", "Close", 10, "partial")
        elif diff <= 7:
            add("Date", f"{diff} days apart", "Far", 5, "partial")
        else:
            add("Date", "More than 7 days apart", "Differs", 0, "differ")
    except (ValueError, TypeError):
        add("Date", "Date could not be read", "Unverified", 0, "unverified")

    # Brand shares the existing 10-point description allocation when provided.
    lost_brand = str(lost.get("brand", "") or "").strip()
    found_brand = str(found.get("brand", "") or "").strip()
    brand_active = bool(lost_brand or found_brand)
    description_points = 5 if brand_active else 10
    if brand_active:
        if not lost_brand or not found_brand:
            add("Brand", "Brand not provided in one report", "Unverified", 0, "unverified")
        elif lost_brand.casefold() == found_brand.casefold():
            add("Brand", "Same brand text", "Match", 5, "match")
        elif set(re.findall(r"[a-z0-9]+", lost_brand.casefold())) & set(
                re.findall(r"[a-z0-9]+", found_brand.casefold())):
            add("Brand", "Partly shared brand text", "Partial", 2, "partial")
        else:
            add("Brand", "Different brand text", "Differs", 0, "differ")

    # Description (10 normally; 5 when sharing its allocation with brand)
    d1, d2 = lost["description"].strip(), found["description"].strip()
    if not d1 or not d2:
            add("Description", "Description not provided in one report", "Unverified", 0, "unverified")
    else:
        stop = {"a", "an", "the", "with", "in", "on", "and", "is", "of", "to"}
        words = lambda t: set(re.findall(r"[a-z0-9]+", t.lower()))   # ignores punctuation: "cover." == "cover"
        common = (words(d1) & words(d2)) - stop
        if len(common) >= 3:
            add("Description", "Many shared key terms", "Similar", description_points, "match")
        elif common:
            add("Description", "Some shared key terms", "Partial", description_points // 2, "partial")
        else:
            add("Description", "Different descriptions", "Differs", 0, "differ")
    return score, rows


def ensure_custody(report):
    """Add a backward-compatible custody state and initial history entry."""
    if report.get("type") != "Found":
        return report
    holder = str(report.get("holder") or "").strip()
    if holder not in CUSTODY_HOLDERS:
        holder = "Finder"
    history = report.get("holder_history")
    if not isinstance(history, list):
        history = []
    if not history:
        history = [{
            "holder": holder,
            "actor": str(report.get("user_email") or "Unknown").strip(),
            "time": str(report.get("date") or "Legacy report"),
            "initial": True,
        }]
    report["holder"] = holder
    report["holder_history"] = history
    return report


def can_update_custody(report, current_user):
    """Return whether the current account may update a found report's holder."""
    if report.get("type") != "Found":
        return False
    if current_user.get("role") == "admin":
        return True
    return str(report.get("user_email") or "").strip().casefold() == str(
        current_user.get("email") or "").strip().casefold()


def transfer_custody(report, holder, actor, timestamp):
    """Update custody and append an auditable transfer entry."""
    ensure_custody(report)
    holder = str(holder).strip()
    if holder not in CUSTODY_HOLDERS:
        raise ValueError("Current holder must be Finder or OSA")
    if report["holder"] == holder:
        return False
    report["holder"] = holder
    report["holder_history"].append({
        "holder": holder,
        "actor": str(actor).strip(),
        "time": str(timestamp).strip(),
    })
    return True


def find_pairs(reports, min_score=MATCH_THRESHOLD):
    """Unresolved lost/found pairs scoring at least min_score, best first."""
    pairs = []
    for lo in (r for r in reports if r["type"] == "Lost" and r["status"] != "Resolved"):
        for fo in (r for r in reports if r["type"] == "Found" and r["status"] != "Resolved"):
            s, rows = calculate_match_score(lo, fo)
            if s >= min_score:
                pairs.append((s, lo, fo, rows))
    return sorted(pairs, key=lambda p: -p[0])


def new_notifications(reports, existing_keys, timestamp, threshold=NOTIFY_THRESHOLD):
    """Create strong-match inbox entries for both report owners, once per recipient."""
    seen = set(existing_keys)
    created = []
    for lost in (r for r in reports if r["type"] == "Lost" and r["status"] == "Searching"):
        for found in (r for r in reports if r["type"] == "Found" and r["status"] == "Reported"):
            score, _ = calculate_match_score(lost, found)
            if score < threshold:
                continue
            pair_key = f"{lost['id']}_{found['id']}"
            recipients = dict.fromkeys(
                str(value or "").strip().casefold()
                for value in (lost.get("user_email", ""), found.get("user_email", ""))
                if str(value or "").strip())
            for recipient in recipients:
                key = f"{pair_key}_{recipient}"
                if key in seen:
                    continue
                seen.add(key)
                created.append({"key": key, "pair_key": pair_key, "recipient": recipient,
                                "item": lost["item"], "score": score, "time": timestamp})
    return created
