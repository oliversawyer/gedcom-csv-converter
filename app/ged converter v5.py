import os
import re
import pandas as pd
import numpy as np
from pathlib import Path
from gedcom.parser import Parser
from gedcom.element.individual import IndividualElement

# ---------- CONFIG ----------
WORK_DIR     = r"C:\Users\olive\OneDrive\Desktop\Python"
GEDCOM_FILE  = r"C:\Users\olive\OneDrive\Desktop\Geneology\Oliver Hudson Sawyer Family Tree.ged"
OUTPUT_XLSX  = r"C:\Users\olive\OneDrive\Desktop\Gengeology\MyTreeData.xlsx"
OUTPUT_CSV   = r"C:\Users\olive\OneDrive\Desktop\Geneology\FamilyTreeData.csv"

# Choose ONE (ID takes precedence). Leave the other blank.
PROBAND_ID   = "@I220047939818@"      # e.g., "@I1234@"  (most reliable)
PROBAND_NAME = "Oliver Hudson Sawyer" # partial/case-insensitive OK (used only if ID not set)
# ----------------------------

# Working directory (optional)
if WORK_DIR:
    os.chdir(WORK_DIR)
print("CWD:", os.getcwd())

# ---------- Parse GEDCOM with encoding fallback ----------
assert Path(GEDCOM_FILE).is_file(), f"GED file not found: {GEDCOM_FILE}"

encodings_to_try = ["utf-8", "utf-8-sig", "cp1252", "latin1"]
ged_text = None
for enc in encodings_to_try:
    try:
        with open(GEDCOM_FILE, "r", encoding=enc) as f:
            ged_text = f.read()
            print(f"[Info] Loaded GEDCOM using encoding: {enc}")
            break
    except UnicodeDecodeError:
        continue
if ged_text is None:
    raise UnicodeDecodeError("All encoding attempts failed. File is not a standard text encoding.")

gedcom_parser = Parser()
# just parse directly from file, let Python handle encodings
# try cp1252 first if utf-8 fails
# ---------- Parse GEDCOM with robust normalization to "0 HEAD" ----------


class ConversionError(Exception):
    """Raised when the GED → CSV conversion cannot proceed."""
    pass



import os, re, tempfile
from pathlib import Path

if not Path(GEDCOM_FILE).is_file():
    raise ConversionError(f"GED file not found: {GEDCOM_FILE}")

gedcom_parser = Parser()

def _normalize_to_utf8_and_slice_head(src_path: str) -> str:
    """Return path to a temp, BOM-free UTF-8 GED with CRLF line endings, sliced so the file starts at '0 HEAD'."""
    with open(src_path, "rb") as f:
        raw = f.read()

    # Handle UTF-16 BOM explicitly
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            text = raw.decode("utf-16")
        except UnicodeDecodeError:
            text = raw.decode("utf-16", errors="ignore")
    else:
        # Remove UTF-8 BOM if present
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        # Try several encodings; last resort keep as latin-1 ignoring errors
        text = None
        for enc in ("utf-8", "utf-8-sig", "mac_roman", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("latin-1", errors="ignore")

    # Strip stray BOM/NULL/zero-width/control chars from the very start
    text = text.lstrip("\ufeff\ufeff\ufeff").lstrip("\x00").lstrip()

    # Find the first real "0 HEAD" (allowing for junk/blank lines before)
    m = re.search(r'(?m)^(?:\s*)0\s+HEAD\b', text)
    if not m:
        # No HEAD anywhere -> not a GEDCOM file
        preview = repr(text[:160])
        raise ConversionError(f'GEDCOM header "0 HEAD" not found in file. First 160 chars: {preview}')

    # Slice so file starts exactly at the 0 of "0 HEAD"
    text = text[m.start():]

    # Normalize line endings to CRLF (GED 5.5 friendly)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\r\n".join(text.split("\n")) + "\r\n"

    # Write normalized copy
    with tempfile.NamedTemporaryFile("w", suffix=".ged", delete=False, encoding="utf-8", newline="\r\n") as tf:
        tf.write(text)
        return tf.name

try:
    # Fast path
    gedcom_parser.parse_file(GEDCOM_FILE)
    print("[Info] Parsed GEDCOM directly.")
except Exception:
    # Normalize + slice to HEAD, then parse
    tmp_norm = _normalize_to_utf8_and_slice_head(GEDCOM_FILE)
    try:
        gedcom_parser.parse_file(tmp_norm)
        print("[Info] Parsed after UTF-8/BOM/CRLF normalization and HEAD slice.")
    finally:
        try: os.remove(tmp_norm)
        except OSError: pass

root_child_elements = gedcom_parser.get_root_child_elements()
# ---------- Helper utilities ----------
def strip_number_prefix(name):
    if not isinstance(name, str):
        return name
    return re.sub(r'^\d+\s*', '', name.strip())

def get_name(ind):
    if not ind:
        return None
    try:
        first, last = ind.get_name()
        return strip_number_prefix(f"{first} {last}".strip())
    except Exception:
        return None

def get_parents(ind):
    if not ind:
        return []
    try:
        return gedcom_parser.get_parents(ind)
    except Exception:
        return []

# ---- Robust event extraction: walk tags and support alternates ----
def _first_child_with_tag(element, tag):
    for ch in element.get_child_elements():
        if ch.get_tag() == tag:
            return ch
    return None

def _child_value(element, tag):
    ch = _first_child_with_tag(element, tag)
    return ch.get_value() if ch else None

def _event_date_place(ind_el, primary_tag, alt_tags=()):
    ev = _first_child_with_tag(ind_el, primary_tag)
    if ev:
        date = _child_value(ev, "DATE")
        plac = _child_value(ev, "PLAC")
        if date or plac:
            return date, plac
    for alt in alt_tags:
        ev = _first_child_with_tag(ind_el, alt)
        if ev:
            date = _child_value(ev, "DATE")
            plac = _child_value(ev, "PLAC")
            if date or plac:
                return date, plac
    return None, None

def get_birth(ind):
    if not ind:
        return None, None
    # CHR/BAPM/BAPT often used as proxy when BIRT missing
    return _event_date_place(ind, "BIRT", alt_tags=("CHR", "BAPM", "BAPT"))

def get_death(ind):
    if not ind:
        return None, None
    # BURI/BUR often present when DEAT missing
    return _event_date_place(ind, "DEAT", alt_tags=("BURI", "BUR"))

# ---- Optional date cleanup (remove ABT/BEF/AFT/CAL/EST/etc.) ----
_ABT_BEFS = re.compile(r"^(ABT|BEF|AFT|CAL|EST|FROM|TO|BET)\b", flags=re.I)

MONTHS = {
    "JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
    "JUL":7,"AUG":8,"SEP":9,"SEPT":9,"OCT":10,"NOV":11,"DEC":12,
    "JANUARY":1,"FEBRUARY":2,"MARCH":3,"APRIL":4,"JUNE":6,
    "JULY":7,"AUGUST":8,"SEPTEMBER":9,"OCTOBER":10,"NOVEMBER":11,"DECEMBER":12
}
QUALIFIER_RE = re.compile(r"\b(ABT|ABOUT|BEF|BEFORE|AFT|AFTER|CAL|EST|FROM|TO|BET|AND|INT|CIRCA|CA)\b\.?", re.I)

def clean_ged_date(s: str | None) -> str | None:
    if not isinstance(s, str): return None
    s = s.replace("\u00A0"," ")            # non-breaking spaces → normal spaces
    s = re.sub(r"[\(\)]", " ", s)          # drop parentheses
    s = QUALIFIER_RE.sub(" ", s)           # remove qualifiers
    s = re.sub(r"[,\-\/]+", " ", s)        # commas/dashes/slashes → spaces (keeps numeric months like 3/1887 meaningful)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s or None

def parse_gedcom_date_robust(s: str | None):
    """
    Return (day, month_name, year, month_num, iso_yyyy_mm_dd_or_None)
    """
    if not isinstance(s, str) or not s.strip():
        return None, None, None, None, None

    raw = s
    s = clean_ged_date(s)
    if not s: 
        return None, None, None, None, None

    up = s.upper()

    # 1) Year: take the LAST 4-digit year present
    years = re.findall(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", up)
    year = int(years[-1]) if years else None

    # 2) Month: look for a named month first
    month_num = None
    month_name = None
    tokens = up.split()
    for t in tokens:
        t_clean = re.sub(r"[^\w]", "", t)
        if t_clean in MONTHS:
            month_num = MONTHS[t_clean]
            month_name = t_clean.title() if len(t_clean) > 3 else t_clean.capitalize()
            break

    # If still no month, try a numeric month preceding the year (e.g., "3 1887" or "03 1887")
    if month_num is None and year is not None:
        m = re.search(r"\b(0?[1-9]|1[0-2])\s+" + str(year) + r"\b", up)
        if m:
            month_num = int(m.group(1))
            month_name = list(MONTHS.keys())[list(MONTHS.values()).index(month_num)]  # pick a canonical abbrev

    # 3) Day: if month exists, try to capture a 1–31 that appears just before the month token
    day = None
    if month_num is not None:
        # Find month position
        month_pos = up.find(month_name.upper()[:3])
        if month_pos == -1:
            # if month came from numeric capture, month_name might be e.g. 'JAN'; fallback: scan tokens
            month_pos = up.find(str(month_num))
        # Look for a day number immediately before the month (… 12 MAR 1887 …)
        mday = re.search(r"\b([0-3]?\d)\b(?=.*\b" + (month_name.upper()[:3] if month_name else str(month_num)) + r"\b)", up)
        if mday:
            d = int(mday.group(1))
            if 1 <= d <= 31:
                day = d

    # 4) Build ISO date if we have enough parts
    iso = None
    if year and month_num and day:
        iso = f"{year:04d}-{month_num:02d}-{day:02d}"
    elif year and month_num:
        iso = f"{year:04d}-{month_num:02d}"
    elif year:
        iso = f"{year:04d}"

    return day, month_name, year, month_num, iso

# ---------- Proband selection ----------
def find_proband():
    # 1) Try ID first
    if PROBAND_ID:
        for el in root_child_elements:
            if isinstance(el, IndividualElement) and el.get_pointer() == PROBAND_ID:
                return el
        # Not found by ID — print some examples to help
        examples = []
        for i, el in enumerate(e for e in root_child_elements if isinstance(e, IndividualElement)):
            if i >= 25:
                break
            nm = get_name(el) or ""
            examples.append(f"{el.get_pointer()}  {nm}")
        raise SystemExit(
            f"Proband ID '{PROBAND_ID}' not found.\nExamples:\n" + "\n".join(examples)
        )

    # 2) Fall back to partial/case-insensitive name
    key = (PROBAND_NAME or "").strip().lower()
    if not key:
        raise SystemExit("Please set PROBAND_ID or PROBAND_NAME in CONFIG.")

    matches = []
    for el in root_child_elements:
        if isinstance(el, IndividualElement):
            nm = (get_name(el) or "").lower()
            if key and key in nm:
                matches.append(el)

    if not matches:
        examples = []
        for i, el in enumerate(e for e in root_child_elements if isinstance(e, IndividualElement)):
            if i >= 40:
                break
            nm = get_name(el) or ""
            examples.append(f"{el.get_pointer()}  {nm}")
        raise SystemExit(
            f"Proband name '{PROBAND_NAME}' not found.\nFirst 40 examples:\n" + "\n".join(examples)
        )

    chosen = matches[0]
    if len(matches) > 1:
        print(f"[Info] Multiple name matches ({len(matches)}). Using first: {chosen.get_pointer()}  {get_name(chosen)}")
    return chosen

# ---------- Upward ancestry walk ----------
# generation=0: proband, 1=parents, 2=grandparents, 3=great-grandparents, 4=2×great, ...
# set lineage_root at generation==3 (the 8 great-grandparents)
def build_ancestry(ind, generation=0, lineage_root=None, visited=None, out=None):
    if visited is None:
        visited = set()
    if out is None:
        out = {}
    if ind is None:
        return out
    pid = ind.get_pointer()
    if pid in visited:
        return out
    visited.add(pid)

    if generation == 3:
        lineage_root = pid

    out[pid] = {
        "generations_above_proband": generation,
        "great_grandparent_line": lineage_root
    }

    for parent in get_parents(ind):
        build_ancestry(parent, generation + 1, lineage_root, visited, out)
    return out

# ---------- Build dataframe ----------
proband = find_proband()
print("Proband pointer:", proband.get_pointer(), "Name:", get_name(proband))

ancestry_data = build_ancestry(proband)

rows = []
for el in root_child_elements:
    if not isinstance(el, IndividualElement):
        continue
    pid = el.get_pointer()
    nm = get_name(el)

    dob, bplace = get_birth(el)
    dod, dplace = get_death(el)
    dob = clean_ged_date(dob)
    dod = clean_ged_date(dod)

    # parents (names only)
    parents = get_parents(el)
    father_name = mother_name = None
    for p in parents:
        try:
            if p.get_gender() == 'M':
                father_name = get_name(p)
            elif p.get_gender() == 'F':
                mother_name = get_name(p)
        except Exception:
            pass

    info = ancestry_data.get(pid, {})
    generations = info.get("generations_above_proband")
    lineage_root_ptr = info.get("great_grandparent_line")

    rows.append({
        "ID": pid,
        "name": nm,
        "DOB": dob,
        "birth_location": bplace,
        "DOD": dod,
        "death_location": dplace,
        "father": father_name,
        "mother": mother_name,
        "generations_above_proband": generations,   # parents=1, grands=2, greats=3, etc.
        "great_grandparent_line_ptr": lineage_root_ptr
    })

df = pd.DataFrame(rows)

# ---------- Tag the 8 great-grandparent roots as GG1..GG8 ----------
ggp_label_map = {}
label_counter = 1
for ptr in df["great_grandparent_line_ptr"]:
    if pd.notna(ptr) and ptr and ptr not in ggp_label_map:
        ggp_label_map[ptr] = f"GG{label_counter}"
        label_counter += 1

ptr_to_name = {row["ID"]: row["name"] for _, row in df.iterrows()}
df["great_grandparent_line"] = df["great_grandparent_line_ptr"].map(lambda p: ggp_label_map.get(p) if pd.notna(p) else None)
df["great_grandparent_name"] = df["great_grandparent_line_ptr"].map(lambda p: ptr_to_name.get(p) if pd.notna(p) else None)

# ---------- Split date components (optional) ----------
dob_parts = df["DOB"].apply(parse_gedcom_date_robust)
dod_parts = df["DOD"].apply(parse_gedcom_date_robust)

df["DOB_day"]        = dob_parts.apply(lambda t: t[0])
df["DOB_month_name"] = dob_parts.apply(lambda t: t[1])
df["DOB_year"]       = dob_parts.apply(lambda t: t[2])
df["DOB_month_num"]  = dob_parts.apply(lambda t: t[3])
df["DOB_iso"]        = dob_parts.apply(lambda t: t[4])

df["DOD_day"]        = dod_parts.apply(lambda t: t[0])
df["DOD_month_name"] = dod_parts.apply(lambda t: t[1])
df["DOD_year"]       = dod_parts.apply(lambda t: t[2])
df["DOD_month_num"]  = dod_parts.apply(lambda t: t[3])
df["DOD_iso"]        = dod_parts.apply(lambda t: t[4])

# ---------- State / Country normalization ----------
us_states = {
    'Alabama','Alaska','Arizona','Arkansas','California','Colorado','Connecticut',
    'Delaware','Florida','Georgia','Hawaii','Idaho','Illinois','Indiana','Iowa',
    'Kansas','Kentucky','Louisiana','Maine','Maryland','Massachusetts','Michigan',
    'Minnesota','Mississippi','Missouri','Montana','Nebraska','Nevada','New Hampshire',
    'New Jersey','New Mexico','New York','North Carolina','North Dakota','Ohio',
    'Oklahoma','Oregon','Pennsylvania','Rhode Island','South Carolina','South Dakota',
    'Tennessee','Texas','Utah','Vermont','Virginia','Washington','West Virginia',
    'Wisconsin','Wyoming'
}
state_abbrev_map = {
    'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California',
    'CO':'Colorado','CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia',
    'HI':'Hawaii','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas',
    'KY':'Kentucky','LA':'Louisiana','ME':'Maine','MD':'Maryland','MA':'Massachusetts',
    'MI':'Michigan','MN':'Minnesota','MS':'Mississippi','MO':'Missouri','MT':'Montana',
    'NE':'Nebraska','NV':'Nevada','NH':'New Hampshire','NJ':'New Jersey','NM':'New Mexico',
    'NY':'New York','NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma',
    'OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina',
    'SD':'South Dakota','TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont',
    'VA':'Virginia','WA':'Washington','WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming'
}
country_aliases = {
    'US':'USA','U.S.':'USA','U.S.A.':'USA','United States':'USA','United States of America':'USA',
    'England':'United Kingdom','UK':'United Kingdom','GB':'United Kingdom','Great Britain':'United Kingdom',
    'Deutschland':'Germany', 'germany':'Germany', 'Wittgenstein':'Germany', 'switzerland':'Switzerland,','swtz':'Switzerland','suisse':'Switzerland'
}

def extract_state_country(location_str):
    if not isinstance(location_str, str):
        return None, None
    parts = [p.strip() for p in location_str.split(',') if p.strip()]
    state = None
    country = None
    # Scan from rightmost to leftmost
    for part in reversed(parts):
        # Country first (with alias normalization)
        if country is None:
            country = country_aliases.get(part, part)
        # State: accept full name or USPS abbrev mapped to full
        if state is None:
            if part in state_abbrev_map:
                state = state_abbrev_map[part]
            elif part in us_states:
                state = part
        if state and country:
            break
    return state, country

df[['birth_state','birth_country']] = df['birth_location'].apply(lambda x: pd.Series(extract_state_country(x)))
df[['death_state','death_country']] = df['death_location'].apply(lambda x: pd.Series(extract_state_country(x)))

# ---------- Quick sanity counts ----------
print("\nNon-null counts:")
for col in ["DOB","birth_location","DOD","death_location","birth_state","birth_country","death_state","death_country"]:
    print(f"{col:18s}", df[col].notna().sum(), "/", len(df))

# ---------- Save ----------
Path(OUTPUT_XLSX).parent.mkdir(parents=True, exist_ok=True)
df.to_excel(OUTPUT_XLSX, index=False)
df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

print(f"\nWrote:\n- {OUTPUT_XLSX}\n- {OUTPUT_CSV}")
print("\nPreview:")
print(df.head(12)[[
    "ID","name","generations_above_proband","great_grandparent_line","great_grandparent_name",
    "DOB","birth_location","birth_state","birth_country",
    "DOD","death_location","death_state","death_country",
    "father","mother"
]])



# ---------------- Country & State dictionaries ----------------
# Map MANY aliases → a single canonical country code string to store
COUNTRY_MAP = {
    # United States
    "usa":"USA","us":"USA","u.s.":"USA","u.s.a.":"USA",
    "united states":"USA","united states of america":"USA","america":"USA",
    # United Kingdom (treat England/Scotland/Wales/Great Britain as UK, adjust if you prefer separate codes)
    "uk":"UK","u.k.":"UK","united kingdom":"UK","great britain":"UK","gb":"UK","gbr":"UK",
    "england":"England","scotland":"Scotland","wales":"Wales","northern ireland":"Northern Ireland",
    # Canada / Mexico
    "canada":"Canada","can":"Canada","ca":"Canada",
    "mexico":"MEX","mex":"MEX",
    'barbados': 'Barbados',
    # Ireland
    "ireland":"Ireland","eir":"Ireland","roi":"Ireland",
    # Western Europe common
    "germany":"Germany","deutschland":"Germany","france":"France","italy":"Italy","spain":"Spaine",
    "netherlands":"Netherlands","sweden":"Sweden","norway":"Norway","denmark":"Denmark",
    "poland":"Poland","switzerland":"Switzerland","austria":"Austria","portugal":"Portugal","belgium":"Belgium",
    "finland":"Finland","scandinavia":"Scandinavia",  # optional umbrella
    # Oceania
    "australia":"Australia","new zealand":"New Zealand","nz":"New Zealand",
    # Others (add as needed)
    "russia":"Russia","china":"China","india":"India","brazil":"Brazil","south africa":"South Africa",
    "czech republic":"Czech Republic","czechia":"Czechia","hungary":"Hungary","romania":"ROU","lithuania":"LTU",
}

# US states: USPS → full name
USPS_TO_STATE = {
    'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California',
    'CO':'Colorado','CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia',
    'HI':'Hawaii','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas',
    'KY':'Kentucky','LA':'Louisiana','ME':'Maine','MD':'Maryland','MA':'Massachusetts',
    'MI':'Michigan','MN':'Minnesota','MS':'Mississippi','MO':'Missouri','MT':'Montana',
    'NE':'Nebraska','NV':'Nevada','NH':'New Hampshire','NJ':'New Jersey','NM':'New Mexico',
    'NY':'New York','NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma',
    'OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina',
    'SD':'South Dakota','TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont',
    'VA':'Virginia','WA':'Washington','WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming'
}
# Full names set for quick membership
US_STATES_FULL = set(USPS_TO_STATE.values())

# ---------------- Normalization helpers ----------------
def _norm_token(s: str) -> str:
    """Normalize a token for matching (lowercase, remove dots & extra spaces)."""
    s = s.strip().lower()
    s = s.replace(".", "")
    s = re.sub(r"\s{2,}", " ", s)
    return s

def _strip_wrappers(s: str) -> str:
    """Remove parentheses and extra spaces from a location part."""
    s = s.replace("(", " ").replace(")", " ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

def split_location_parts(loc: str) -> list[str]:
    # Split on commas, trim, drop empties
    parts = []
    for p in loc.split(","):
        p2 = _strip_wrappers(p)
        if p2:
            parts.append(p2)
    return parts

def detect_country_state_city(loc: str):
    """
    From a raw location string, detect:
      - country (via COUNTRY_MAP, code like 'USA')
      - state (US only; full name)
      - city (remaining text once country/state parts removed, joined by ', ')
    Strategy:
      1) Find a country alias anywhere among parts (right-to-left is typical but we scan all).
      2) Find a US state by USPS or full name.
      3) Remove the exact matched parts for state/country from parts (case-insensitive).
      4) Join leftovers as city.
    """
    if not isinstance(loc, str) or not loc.strip():
        return None, None, None

    parts = split_location_parts(loc)

    # Build parallel normalized tokens for matching
    norm_parts = [_norm_token(p) for p in parts]

    # 1) Country detection (any part)
    country = None
    matched_country_idx = None
    for i, npart in enumerate(norm_parts):
        # direct match
        if npart in COUNTRY_MAP:
            country = COUNTRY_MAP[npart]
            matched_country_idx = i
            break
        # try removing trailing punctuation etc already handled; also try singular/plural no-op

    # 2) State detection (US only)
    state = None
    matched_state_idx = None
    for i, (raw, npart) in enumerate(zip(parts, norm_parts)):
        # USPS 2-letter?
        up = raw.strip().upper()
        if up in USPS_TO_STATE:
            state = USPS_TO_STATE[up]
            matched_state_idx = i
            break
        # Full state name?
        if raw in US_STATES_FULL:
            state = raw
            matched_state_idx = i
            break

    # If a US state was found but no explicit country, set to USA
    if state and not country:
        country = "USA"

    # 3) Remove matched segments from the parts to get city
    remove_idxs = set(idx for idx in (matched_country_idx, matched_state_idx) if idx is not None)
    city_parts = [p for j, p in enumerate(parts) if j not in remove_idxs]
    city = ", ".join(city_parts) if city_parts else None

    return city, state, country

# ---------------- Apply to birth/death locations ----------------
for col_prefix in ["birth", "death"]:
    loc_col = f"{col_prefix}_location"
    city_col, state_col, country_col = f"{col_prefix}_city", f"{col_prefix}_state", f"{col_prefix}_country"

    parsed = df[loc_col].apply(detect_country_state_city)
    df[city_col]    = parsed.apply(lambda t: t[0] if t else None)
    df[state_col]   = parsed.apply(lambda t: t[1] if t else None)
    df[country_col] = parsed.apply(lambda t: t[2] if t else None)

# --- quick audit ---
print("\nCountry counts (birth):")
print(df["birth_country"].value_counts(dropna=False).head(20))
print("\nState counts (birth):")
print(df["birth_state"].value_counts(dropna=False).head(20))
print("\nExample parsed rows:")
print(df.loc[:, ["birth_location","birth_city","birth_state","birth_country"]].head(10).to_string(index=False))

def extract_year(date_str):
    if not isinstance(date_str, str):
        return None
    match = re.search(r'\b(\d{4})\b', date_str)
    return int(match.group(1)) if match else None

df['birth_year'] = df['DOB'].apply(extract_year)
df['death_year'] = df['DOD'].apply(extract_year)



df['age_at_death'] = df['death_year'] - df['birth_year']

df['DNA%'] = 0.5**(df['generations_above_proband'])


df = df.sort_values(by=['generations_above_proband','great_grandparent_name','DOD_year'], ascending=[True,True,True])



import re
import pandas as pd

def add_notes_from_name(df, name_col="name", notes_col="Notes", in_place=True):
    # ---- Nobility titles ----
    nobility_patterns = [
        (r"\bqueen\b",                         "Queen"),
        (r"\bking\b",                          "King"),
        (r"\bprincess\b",                      "Princess"),
        (r"\bprince\b",                        "Prince"),
        (r"\bduchess\b",                       "Duchess"),
        (r"\bduke\b",                          "Duke"),
        (r"\bmarquess\b|\bmarquis\b",          "Marquess/Marquis"),
        (r"\bmarchioness\b",                   "Marchioness"),
        (r"\bviscountess\b",                   "Viscountess"),
        (r"\bviscount\b",                      "Viscount"),
        (r"\bcountess\b",                      "Countess"),
        (r"\bcount\b",                         "Count"),
        (r"\bbaroness\b",                      "Baroness"),
        (r"\bbaron\b",                         "Baron"),
        (r"\blord\b",                          "Lord"),
        (r"\blady\b",                          "Lady"),
        (r"\bsir\b",                           "Sir"),
        (r"\bdame\b",                          "Dame"),
        (r"\bknight\b",                        "Knight"),
    ]

    # ---- Military ranks ----
    military_patterns = [
        (r"\blieutenant\s+general\b|\blt\.?\s*gen\.?\b",          "Lt. Gen."),
        (r"\bmajor\s+general\b|\bmaj\.?\s*gen\.?\b",              "Maj. Gen."),
        (r"\bbrigadier\s+general\b|\bbrig\.?\s*gen\.?\b|\bbg\b",  "Brig. Gen."),
        (r"\bgeneral\b|\bgen\.?\b",                               "Gen."),
        (r"\bvice\s+admiral\b|\bvadm\b",                          "VADM"),
        (r"\brear\s+admiral\b|\bradm\b",                          "RADM"),
        (r"\badmiral\b|\badm\.?\b",                               "Adm."),
        (r"\blieutenant\s+colonel\b|\blt\.?\s*col\.?\b|\bltc\b",  "Lt. Col."),
        (r"\bcolonel\b|\bcol\.?\b",                               "Col."),
        (r"\bmajor\b(?!ity)|\bmaj\.?\b",                          "Maj."),
        (r"\bcaptain\b(?!\w)|\bcapt\.?\b|\bcpt\.?\b",             "Capt."),
        (r"\bfirst\s+lieutenant\b|\b1st\s*lt\b|\b1lt\b|\b1st\s*lieut\.?\b", "1st Lt."),
        (r"\bsecond\s+lieutenant\b|\b2nd\s*lt\b|\b2lt\b|\b2d\s*lt\b",       "2nd Lt."),
        (r"\blieutenant\s+commander\b|\blt\.?\s*cmdr\.?\b|\blcdr\b",        "Lt. Cmdr."),
        (r"\bcommander\b|\bcdr\b|\bcmdr\b",                       "Cmdr"),
        (r"\bensign\b|\bens\.?\b",                                "Ens."),
        (r"\bwarrant\s+officer\b|\bwo\d?\b",                      "WO"),
        (r"\bsergeant\s+major\b|\bsgm\b|\bsma\b",                 "Sgt. Maj."),
        (r"\bmaster\s+sergeant\b|\bmsg\b",                        "MSgt"),
        (r"\bfirst\s+sergeant\b|\b1st\s*sgt\b|\b1sg\b",           "1st Sgt."),
        (r"\bgunnery\s+sergeant\b|\bgysgt\b",                     "GySgt"),
        (r"\bstaff\s+sergeant\b|\bssgt\b",                        "SSgt"),
        (r"\bsergeant\b|\bsgt\.?\b",                              "Sgt."),
        (r"\blance\s+corporal\b|\blcpl\b",                        "LCpl"),
        (r"\bcorporal\b|\bcpl\.?\b",                              "Cpl."),
        (r"\bspecialist\b|\bspc\b",                               "Spc."),
        (r"\bprivate\s+first\s+class\b|\bpfc\b",                  "PFC"),
        (r"\bprivate\b|\bpvt\.?\b|\bpte\.?\b",                    "Pvt."),
        (r"\bseaman\b|\bsn\b",                                    "Seaman"),
        (r"\bmidshipman\b|\bmidn\b",                              "Midshipman"),
        (r"\bairman\b|\bamn\b",                                   "Airman"),
        (r"\bsailor\b",                                           "Sailor"),
    ]

    # ---- Wars / conflicts ----
    war_patterns = [
        (r"\bking\s+phil(?:ip|lips?)'?s?\s+war\b",                "King Philips War"),
        (r"\bpequot\s+war\b",                                     "Pequot War"),
        (r"\bfrench\s+and\s+indian\s+war\b|\bseven\s+years'?[\s-]*war\b", "French & Indian War"),
        (r"\bking\s+williams?'?\s+war\b",                         "King William's War"),
        (r"\bqueen\s+annes?'?\s+war\b",                           "Queen Anne's War"),
        (r"\bking\s+georges?'?\s+war\b",                          "King George's War"),
        (r"\brevolutionary\s+war\b|\bamerican\s+revolution\b|\bwar\s+of\s+independence\b", "Revolutionary War"),
        (r"\bwar\s+of\s+1812\b",                                  "War of 1812"),
        (r"\bmexican[-\s]*american\s+war\b",                      "Mexican–American War"),
        (r"\bspan(?:ish)?[-\s]*american\s+war\b|\bspan[-\s]*am\s+war\b", "Spanish–American War"),
        (r"\b(civil\s+war|union\s+army|confederate\s+army|c\.?s\.?a\.?)\b", "US Civil War"),
        (r"\b(ww1|wwi|world\s+war\s*i|first\s+world\s+war)\b",    "World War I"),
        (r"\b(ww2|wwii|world\s+war\s*ii|second\s+world\s+war)\b", "World War II"),
        (r"\bkorean\s+war\b",                                     "Korean War"),
        (r"\bvietnam\s+(war|conflict)\b",                         "Vietnam War"),
        (r"\bgulf\s+war\b|\boperation\s+desert\s+storm\b",        "Gulf War"),
        (r"\biraq\s+war\b|\boperation\s+iraqi\s+freedom\b",       "Iraq War"),
        (r"\bwar\s+in\s+afghanistan\b|\boperation\s+enduring\s+freedom\b", "War in Afghanistan"),
        (r"\bD\.?A\.?R\.?\b|\bS\.?A\.?R\.?\b",                    "Revolutionary War (DAR/SAR)"),
    ]

    # compile regexes once
    nobility_rx = [(re.compile(p, re.I), label) for p, label in nobility_patterns]
    military_rx = [(re.compile(p, re.I), label) for p, label in military_patterns]
    war_rx      = [(re.compile(p, re.I), label) for p, label in war_patterns]

    def classify(text):
        s = "" if pd.isna(text) else str(text)
        tags = []
        nob = {label for rx, label in nobility_rx if rx.search(s)}
        mil = {label for rx, label in military_rx if rx.search(s)}
        war = {label for rx, label in war_rx      if rx.search(s)}
        for label in sorted(nob):
            tags.append(f"Nobility: {label}")
        for label in sorted(mil):
            tags.append(f"Military: {label}")
        for label in sorted(war):
            tags.append(f"War: {label}")
        return "; ".join(tags) if tags else ""

    # choose working df
    out = df if in_place else df.copy()

    # ensure column exists
    if name_col not in out.columns:
        raise KeyError(f"Column '{name_col}' not found in DataFrame.")

    # write new column in place
    out[notes_col] = out[name_col].apply(classify)  # <-- key line

    return out






add_notes_from_name(df, name_col="name", notes_col="Notes")








#Reorder Columns
new_column_order = ['name', 'birth_year', 'birth_city','birth_state','birth_country','death_year','death_city','death_state','death_country','age_at_death','father','mother','generations_above_proband','great_grandparent_name','DNA%']

# Reorder the columns
df_reordered = df[new_column_order]




df_reordered.to_csv('FamilyTreeData.csv')



### END MAIN LOGIC ###






### TESTING ###



Test = df[df['name'] =='Agnes Stewart'].reset_index()

Test.loc[0,'birth_year']













### Stats and Summaries ###



# Ensure DOB_year is numeric
df["birth_year"] = pd.to_numeric(df.get("birth_year"), errors="coerce")


# --- Ensure numeric fields ---
df["birth_year"] = pd.to_numeric(df.get("birth_year"), errors="coerce")
df["death_year"] = pd.to_numeric(df.get("death_year"), errors="coerce")
df["generations_above_proband"] = pd.to_numeric(df.get("generations_above_proband"), errors="coerce")




# Compute age at death
df["age_at_death"] = df["death_year"] - df["birth_year"]
df.loc[~df["age_at_death"].between(0, 120), "age_at_death"] = np.nan  # only plausible ages


# --- Summarize by GG branch ---

#Add average age (life expectancy)
#Split by GG


df_valid = df.dropna(subset=["great_grandparent_name", "birth_year", "generations_above_proband"])

summary = (df_valid.groupby("great_grandparent_name")
             .agg(
                 ancestor_count=("ID","count"),
                 furthest_back_birth_year=("birth_year","min"),
                 furthest_back_generation=("generations_above_proband","max"),
                 average_life_expectancy=("age_at_death","mean")
             )
             .reset_index()
             .sort_values("great_grandparent_name"))



summary['average_life_expectancy'] = round(summary['average_life_expectancy'],0).astype(int)







# --- Filter to rows that have a GG root name ---
base = df.dropna(subset=["great_grandparent_name"])

# --- Core summary by GG root name ---
core = (base.groupby("great_grandparent_name")
            .agg(
                ancestor_count=("ID","count"),
                furthest_back_birth_year=("birth_year","min"),
                furthest_back_generation=("generations_above_proband","max")
            )
            .reset_index())

# --- Compute per-generation ranges for age-at-death ---
per_gen = (base.dropna(subset=["generations_above_proband"])
              .groupby(["great_grandparent_name","generations_above_proband"])
              .agg(
                  age_min=("age_at_death","min"),
                  age_max=("age_at_death","max"),
                  birth_min=("birth_year","min"),
                  birth_max=("birth_year","max")
              )
              .reset_index())

per_gen["age_diff"] = per_gen["age_max"] - per_gen["age_min"]
per_gen["birth_span"] = per_gen["birth_max"] - per_gen["birth_min"]

# --- Collapse to branch (GG root name) ---
max_diffs = (per_gen.groupby("great_grandparent_name")
                   .agg(
                       max_age_diff_per_generation=("age_diff","max"),
                       max_birthyear_span_per_generation=("birth_span","max")
                   )
                   .reset_index())

# --- Merge into summary ---
summary = core.merge(max_diffs, on="great_grandparent_name", how="left")

# Sort alphabetically by name (or re-order manually if you want)
summary = summary.sort_values("great_grandparent_name")




print(summary)
























import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

LINE_COL   = 'great_grandparent_name'
COUNTRY    = 'birth_country'
GEN_PROB   = 'generations_above_proband'
DNA_COL    = 'pct_dna_proband'      # % of proband DNA
GGP_DEPTH  = 3
TARGET_PER_GEN = 12.5               # each column should sum to 12.5

df_w = df.copy()
usa_like = {'US','U.S.','United States','United States of America'}
df_w[COUNTRY] = df_w[COUNTRY].replace(list(usa_like), 'USA')

df_w = df_w.dropna(subset=[LINE_COL, GEN_PROB]).copy()
df_w[GEN_PROB] = df_w[GEN_PROB].astype(int)

# If missing, compute the DNA % for each person
if DNA_COL not in df_w.columns:
    df_w[DNA_COL] = (0.5 ** df_w[GEN_PROB]) * 100.0

# Only ancestors ABOVE the GG (4,5,6,...)
df_w = df_w[df_w[GEN_PROB] >= (GGP_DEPTH + 1)].copy()

# Pedigree-collapse guard: dedupe by person within a line (keep shortest path)
if 'ID' in df_w.columns:
    df_w = (df_w.sort_values([LINE_COL, 'ID', GEN_PROB])
                .drop_duplicates([LINE_COL, 'ID'], keep='first'))

# ---------- sum KNOWN country DNA per (line, generation) ----------
unknown_like = {'Unknown','Uknown','None','', None}
known_mask = df_w[COUNTRY].notna() & ~df_w[COUNTRY].isin(unknown_like)

known = (df_w[known_mask]
         .groupby([LINE_COL, COUNTRY, GEN_PROB], as_index=False)[DNA_COL]
         .sum()
         .rename(columns={DNA_COL: 'dna_pct'}))

# ---------- scale down if known > 12.5 in any (line, gen) ----------
kn_sum = known.groupby([LINE_COL, GEN_PROB])['dna_pct'].sum().reset_index(name='known_sum')
known = known.merge(kn_sum, on=[LINE_COL, GEN_PROB], how='left')
scale = (TARGET_PER_GEN / known['known_sum']).clip(upper=1.0)   # <1 when we need to shrink
known['dna_pct_adj'] = known['dna_pct'] * scale

# ---------- residual "Unknown" so each column sums to 12.5 ----------
adj_sum = (known.groupby([LINE_COL, GEN_PROB])['dna_pct_adj']
                .sum().reset_index(name='adj_sum'))
residual = adj_sum.copy()
residual['dna_pct_adj'] = (TARGET_PER_GEN - residual['adj_sum']).clip(lower=0)
residual[COUNTRY] = 'Unknown'
residual = residual[[LINE_COL, COUNTRY, GEN_PROB, 'dna_pct_adj']]

agg = pd.concat([
    known[[LINE_COL, COUNTRY, GEN_PROB, 'dna_pct_adj']],
    residual
], ignore_index=True).rename(columns={'dna_pct_adj': 'dna_pct'})

# ---------- plot: one heatmap per GG (x = generation above proband) ----------
sns.set_style("whitegrid")

for gg, sub in agg.groupby(LINE_COL):
    sub = sub.copy()

    totals = sub.groupby(COUNTRY)['dna_pct'].sum().sort_values(ascending=False)
    order = [c for c in totals.index if c != 'Unknown'] + (['Unknown'] if 'Unknown' in totals.index else [])
    sub[COUNTRY] = pd.Categorical(sub[COUNTRY], categories=order, ordered=True)

    heat = (sub.pivot(index=COUNTRY, columns=GEN_PROB, values='dna_pct')
               .fillna(0)
               .sort_index())
    heat = heat.reindex(sorted(heat.columns), axis=1)

    plt.figure(figsize=(11, max(4, 0.42 * len(heat.index))))
    ax = sns.heatmap(
        heat, annot=True, fmt='.2f', linewidths=.4, cbar=True,
        cmap='Blues', vmin=0, vmax=TARGET_PER_GEN
    )
    ax.set_title(f'{gg}: Country × Generation above Proband (DNA %; each gen sums to 12.5)')
    ax.set_xlabel('Generation above Proband')
    ax.set_ylabel('Birth Country')
    plt.tight_layout()
    plt.show()
    # --- State x Generation heatmaps from your GEDCOM DF ---
# Assumes your DataFrame is named `df` and includes:
#   great_grandparent_name, birth_state (blank for non-US), DNA% (1, 0.5, 0.25, ...)
# Optional: generations_above_proband (we'll derive it if missing)








# ==============================================================
#  State × Generation Heatmaps (12.5 per generation per GG)
# ==============================================================

import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import os, re

BASE_PER_GEN = 12.5          # each GG×generation totals 12.5
MIN_PCT_BUCKET = None        # e.g., 0.20 to bucket tiny states into "Other (US)"
EPS = 1e-9

# --------------------------------------------------------------
# 0) Cleaning / Prep
# --------------------------------------------------------------
def prepare_birth_state(df, source_col="birth_state", target_col="birth_state_clean"):
    """Blank/NaN -> 'Non-US'; normalize casing; robust to mixed types/ndarrays."""
    def _clean(x):
        if pd.isna(x): return ""
        return str(x).strip()
    state = pd.Series(map(_clean, df[source_col]), index=df.index)
    # your convention: blank means outside US
    out = state.where(state.ne(""), "Non-US")
    # tidy casing, but keep "Non-US" canonical
    out = out.str.title().replace({"Non-Us": "Non-US"})
    df[target_col] = out
    return df

def ensure_generations_from_dna(df, dna_col="DNA%"):
    """Create generations_above_proband if missing. Accepts fractions or percents."""
    if "generations_above_proband" in df.columns:
        return df
    dna_raw = pd.to_numeric(df[dna_col], errors="coerce")
    frac = dna_raw.where(dna_raw <= 1.0000001, dna_raw / 100.0)
    gens = np.log2(1.0 / frac)
    df["generations_above_proband"] = gens.round().astype("Int64").astype(int)
    return df

def ensure_dna_pct_of_proband(df, dna_col="DNA%"):
    """Create dna_pct_of_proband on 0–100 scale. Accepts fractions or percents."""
    dna_raw = pd.to_numeric(df[dna_col], errors="coerce")
    frac = dna_raw.where(dna_raw <= 1.0000001, dna_raw / 100.0)
    df["dna_pct_of_proband"] = frac * 100.0
    return df

# --------------------------------------------------------------
# 1) Aggregate + Normalize (downscale >12.5; top-up <12.5 as Unknown)
# --------------------------------------------------------------
def build_state_counts(df):
    gcols   = ["great_grandparent_name", "generations_above_proband"]
    sc_cols = gcols + ["birth_state_clean"]

    # Sum DNA% per state within each GG×Gen
    state_counts = (
        df.groupby(sc_cols, dropna=False)["dna_pct_of_proband"]
          .sum().reset_index(name="dna_pct")
    )

    # Scale DOWN any GG×Gen that exceeds 12.5 (preserve proportions)
    sums = state_counts.groupby(gcols)["dna_pct"].sum().reset_index(name="sum_gen")
    state_counts = state_counts.merge(sums, on=gcols, how="left")
    state_counts["scale"] = np.where(
        state_counts["sum_gen"] > (BASE_PER_GEN + EPS),
        BASE_PER_GEN / state_counts["sum_gen"],
        1.0
    )
    state_counts["dna_pct"] = state_counts["dna_pct"] * state_counts["scale"]
    state_counts = state_counts.drop(columns=["sum_gen", "scale"])

    # After scaling, add 'Unknown' remainder where needed
    sums2 = state_counts.groupby(gcols)["dna_pct"].sum().reset_index(name="sum_gen2")
    state_counts = state_counts.merge(sums2, on=gcols, how="left")
    state_counts["remainder"] = (BASE_PER_GEN - state_counts["sum_gen2"]).clip(lower=0)
    need_unknown = state_counts.loc[state_counts["remainder"] > EPS, gcols].drop_duplicates()

    if not need_unknown.empty:
        rem = (
            state_counts.merge(need_unknown, on=gcols, how="inner")
                        .groupby(gcols)["remainder"].first().reset_index()
        )
        unknown_rows = rem.assign(birth_state_clean="Unknown", dna_pct=lambda d: d["remainder"])
        unknown_rows = unknown_rows[gcols + ["birth_state_clean", "dna_pct"]]
        state_counts = pd.concat(
            [state_counts[gcols + ["birth_state_clean", "dna_pct"]], unknown_rows],
            ignore_index=True
        )
    else:
        state_counts = state_counts[gcols + ["birth_state_clean", "dna_pct"]]

    # Optional: collapse tiny states into "Other (US)"
    if MIN_PCT_BUCKET:
        def _collapse_small(group, threshold=MIN_PCT_BUCKET):
            small = group["dna_pct"] < threshold
            if small.any():
                other = group.loc[small, "dna_pct"].sum()
                group = group.loc[~small]
                if other > 0:
                    group = pd.concat(
                        [group,
                         pd.DataFrame([{
                             "great_grandparent_name": group["great_grandparent_name"].iloc[0],
                             "generations_above_proband": group["generations_above_proband"].iloc[0],
                             "birth_state_clean": "Other (US)",
                             "dna_pct": other
                         }])],
                        ignore_index=True
                    )
            return group
        state_counts = (
            state_counts.groupby(gcols, group_keys=False).apply(_collapse_small).reset_index(drop=True)
        )

    # Quick integrity check (optional)
    chk = state_counts.groupby(gcols)["dna_pct"].sum().reset_index()
    bad = chk[~np.isclose(chk["dna_pct"], BASE_PER_GEN, atol=1e-6)]
    if not bad.empty:
        print("WARNING: some slices not at 12.5 after normalization (showing first few):")
        print(bad.head())
    return state_counts

# --------------------------------------------------------------
# 2) Plotting (Non-US then Unknown at bottom)
# --------------------------------------------------------------
def plot_state_heatmap_for_gg(states_df, gg_name, vmax=BASE_PER_GEN):
    """Rows=states; cols=generations. Always put 'Non-US' then 'Unknown' at bottom."""
    dfg = states_df[states_df["great_grandparent_name"] == gg_name].copy()
    if dfg.empty:
        print(f"No rows for {gg_name}")
        return

    # Canonicalize labels just in case
    dfg["birth_state_clean"] = dfg["birth_state_clean"].replace(
        {"NON-US": "Non-US", "Non-Us": "Non-US", "UNKNOWN": "Unknown"}
    )

    gens = sorted(dfg["generations_above_proband"].dropna().unique())

    # Order normal states by total across gens (desc)
    totals = dfg.groupby("birth_state_clean")["dna_pct"].sum().sort_values(ascending=False)
    specials = {"Non-US", "Unknown"}
    normal_states = [s for s in totals.index if s not in specials]

    # Final row order: normal states … then Non-US (if present) … then Unknown (if present)
    states_present = set(dfg["birth_state_clean"].unique())
    states_order = normal_states
    if "Non-US" in states_present:
        states_order.append("Non-US")
    if "Unknown" in states_present:
        states_order.append("Unknown")

    pivot = (dfg.pivot_table(index="birth_state_clean",
                             columns="generations_above_proband",
                             values="dna_pct", aggfunc="sum")
               .reindex(index=states_order, columns=gens))

    plt.figure(figsize=(12, 4 + 0.25 * max(8, len(states_order))))
    ax = sns.heatmap(
        pivot.fillna(0), cmap="Blues", vmin=0, vmax=vmax,
        annot=True, fmt=".2f",
        cbar_kws={"label": "DNA % (each generation sums to 12.5)"}
    )
    ax.set_title(f"{gg_name}: State × Generation above Proband (DNA %; each gen sums to 12.5)")
    ax.set_xlabel("Generation above Proband")
    ax.set_ylabel("Birth State")
    plt.tight_layout()
    plt.show()

def plot_all_state_heatmaps(states_df, outdir="state_heatmaps"):
    os.makedirs(outdir, exist_ok=True)
    def slug(s): return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)).strip("_")
    gg_list = sorted(states_df["great_grandparent_name"].dropna().unique().tolist())
    for gg in gg_list:
        plot_state_heatmap_for_gg(states_df, gg)
        plt.savefig(os.path.join(outdir, f"state_heatmap_{slug(gg)}.png"),
                    dpi=200, bbox_inches="tight")
        plt.close()

# --------------------------------------------------------------
# 3) RUN (assumes `df` already exists in memory)
# --------------------------------------------------------------
# Make a safe working copy
df = df.copy()

# Prep columns
df = prepare_birth_state(df, "birth_state", "birth_state_clean")
df = ensure_generations_from_dna(df, "DNA%")
df = ensure_dna_pct_of_proband(df, "DNA%")

# Build normalized table
state_counts = build_state_counts(df)

# Quick preview
print("state_counts preview:")
print(state_counts.head(10), "\n")

# Plot first GG so you can see it immediately
gg_list = sorted(state_counts["great_grandparent_name"].dropna().unique().tolist())
if gg_list:
    print("Plotting first GG:", gg_list[0])
    plot_state_heatmap_for_gg(state_counts, gg_list[0])

# Plot & save all
plot_all_state_heatmaps(state_counts)
print("Saved PNGs to ./state_heatmaps/")













df.to_csv('FamilyTreeData.csv',index=True)
