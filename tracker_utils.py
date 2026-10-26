"""Pure helper logic for the Tender Tracker (no Streamlit, no database access) so it can be tested on its own."""
import io
import re
from datetime import date, datetime

import pandas as pd

# ---------------------------------------------------------------------------
# Small cleaning helpers
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def norm_header(h):
    """'Actual provisional Notification date ' -> 'actual provisional notification date' (case/space/punctuation-proof)."""
    return re.sub(r"[^a-z0-9]+", " ", str(h).strip().lower()).strip()


def parse_date(v):
    """Any date-ish value -> 'YYYY-MM-DD' or '' (blank). Returns (text, ok). Empty input is ok=True.
    Day-first is used for non-ISO text like 01/07/2025 (Rwanda format)."""
    if v is None: return "", True
    if isinstance(v, float) and pd.isna(v): return "", True
    if v is pd.NaT: return "", True
    if isinstance(v, (pd.Timestamp, datetime, date)):
        try: return pd.Timestamp(v).strftime("%Y-%m-%d"), True
        except Exception: return "", False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < float(v) < 80000:      # Excel serial date
            return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))).strftime("%Y-%m-%d"), True
        return "", False
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "nat", "none", "-"): return "", True
    try:
        ts = pd.to_datetime(s[:10], format="%Y-%m-%d", errors="raise") if _ISO_RE.match(s) else pd.to_datetime(s, dayfirst=True, errors="raise")
        return ts.strftime("%Y-%m-%d"), True
    except Exception:
        return "", False


def parse_budget(v):
    """'1,200,000 FRW' -> 1200000.0. Returns (number, ok). Empty is ok (0.0)."""
    if v is None or (isinstance(v, float) and pd.isna(v)): return 0.0, True
    if isinstance(v, (int, float)) and not isinstance(v, bool): return float(v), True
    s = re.sub(r"(?i)frw|rwf|\s", "", str(v)).replace(",", "")
    if s == "" or s.lower() in ("nan", "none", "-"): return 0.0, True
    try: return float(s), True
    except ValueError: return 0.0, False


def clean_text(v):
    """Cell -> tidy string ('' for blanks, 1.0 -> '1')."""
    if v is None or v is pd.NaT: return ""
    if isinstance(v, float):
        if pd.isna(v): return ""
        if v.is_integer(): return str(int(v))
    if isinstance(v, (pd.Timestamp, datetime, date)):
        try: return "" if pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d")      # NaT is a datetime subclass: must be caught
        except (ValueError, TypeError): return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "nat", "none") else s


# ---------------------------------------------------------------------------
# Inline grid edits  ->  list of DB updates (vectorised: no per-row DataFrame filtering)
# ---------------------------------------------------------------------------
def _raw_str(s):
    """Fast first-pass representation: text, blanks as '', whitespace trimmed."""
    return s.astype(object).where(s.notna(), "").astype(str).str.strip()


def _same_value(old_txt, new_txt, is_date):
    """Second pass, run ONLY for cells whose raw text differs: is it really a different value?"""
    if is_date:
        o, ok_o = parse_date(old_txt)
        n, ok_n = parse_date(new_txt)
        if ok_o and ok_n: return o == n
        return False
    try: return float(old_txt) == float(new_txt)          # 500000000.0 vs 500000000 is not an edit
    except (TypeError, ValueError): return False


def compute_inline_changes(old_df, edited_df, editable_cols, date_cols, rename_to_db):
    """Compare the table as saved in the database (old_df) with what the grid sent back (edited_df).
    Returns (updates, date_changed) where updates = [(db_id, db_col, new_value), ...].
    Rows are matched on the hidden 'id' column (falls back to the tender reference number)."""
    if edited_df is None or len(edited_df) == 0 or old_df is None or len(old_df) == 0: return [], False
    new = edited_df.copy()
    if "id" in new.columns and "id" in old_df.columns:
        new["__key"] = pd.to_numeric(new["id"], errors="coerce")
        old = old_df.assign(__key=pd.to_numeric(old_df["id"], errors="coerce"))
    else:
        ref = "Tender reference number"
        new["__key"] = new[ref].astype(str).str.strip()
        old = old_df.assign(__key=old_df[ref].astype(str).str.strip())
    new = new.dropna(subset=["__key"]).drop_duplicates("__key").set_index("__key")
    old = old.dropna(subset=["__key"]).drop_duplicates("__key").set_index("__key")
    common = new.index.intersection(old.index)
    if len(common) == 0: return [], False
    new, old = new.loc[common], old.loc[common]
    db_ids = pd.to_numeric(old["id"], errors="coerce").astype(int)

    updates, date_changed = [], False
    for col in new.columns:
        if col not in editable_cols or col not in old.columns: continue
        is_date = col in date_cols
        o, n = _raw_str(old[col]), _raw_str(new[col])
        diff = o.ne(n)
        if not diff.any(): continue                               # whole column identical -> nothing more to do
        for key in diff[diff].index:
            ov, nv = o.loc[key], n.loc[key]
            if _same_value(ov, nv, is_date): continue
            if is_date:
                nv, ok = parse_date(nv)                           # store dates as YYYY-MM-DD (blank if unreadable, like before)
                date_changed = True
            updates.append((int(db_ids.loc[key]), rename_to_db.get(col, col), nv))
    return updates, date_changed


# ---------------------------------------------------------------------------
# Import: column matching + row cleaning
# ---------------------------------------------------------------------------
ALIASES = {
    "S/N": ["sn", "no", "number", "tender no", "tender no s n", "serial", "serial no", "serial number", "item no"],
    "Tender reference number": ["tender ref", "tender reference", "tender ref no", "tender ref number", "tender reference no", "reference",
                                "reference number", "reference no", "ref", "ref no", "ref number", "tender ref."],
    "Title of the tender": ["title", "tender title", "title of tender", "description", "tender description"],
    "Current status": ["status", "tender status"],
    "Method of tender": ["method", "procurement method", "tender method"],
    "Responsible officer": ["officer", "procurement officer"],
    "ITC Team": ["itc"],
    "Budget FRW": ["budget", "budget frw", "budget rwf", "estimated budget"],
    "Source of funds": ["funds", "source of fund", "funding source"],
    "SMT date": ["smt"],
    "Comments ": ["comments", "comment", "remarks", "remark", "notes"],
    "Date awarded": ["awarded date", "award date", "date of award"],
}

# Order used for the Excel template, the "paste without a header" case and the typed table.
TEMPLATE_ORDER = [
    "S/N", "Tender reference number", "Title of the tender", "Current status", "Category", "Method of tender", "Responsible officer",
    "ITC Team", "Budget FRW", "Source of funds", "SMT date", "Submitted date to ITC for TD approval", "Feedback from ITC on TD (date)",
    "Planned Publication date", "Actual Publication date", "Planned Bid opening date", "Actual Bid Opening date",
    "Date bids are submitted for ITC evaluation", "Date evaluation report is released from ITC", "Planned Provisional Notification date",
    "Actual provisional Notification date ", "Planned Contract signing date", "Actual contract date", "Date awarded", "Comments ",
]

COLUMN_HELP = {
    "S/N": "Serial number on your plan (optional).",
    "Tender reference number": "REQUIRED. The unique reference of the tender. If left blank (but a title is given) one like N/A-1 is generated.",
    "Title of the tender": "What is being procured.",
    "Current status": "One of the status options (e.g. Planned, Published, Under Evaluation, Awarded, Cancelled, Completed). Blank = the default you choose.",
    "Category": "Tender category (as in the dropdown list).",
    "Method of tender": "NCB, ICB, RFQ ... (as in the dropdown list).",
    "Responsible officer": "Officer in charge.",
    "ITC Team": "ITC1, ITC2 ... (as in the dropdown list).",
    "Budget FRW": "Number only, e.g. 25000000. Commas and 'FRW' are ignored.",
    "Source of funds": "Funding source (optional).",
    "Comments ": "Free comments (optional).",
}


def build_header_lookup(targets):
    """normalised header text -> canonical column name, for the columns that exist in this tracker."""
    lookup = {}
    for t in targets: lookup[norm_header(t)] = t
    for canon, aliases in ALIASES.items():
        if canon in targets:
            for a in aliases: lookup.setdefault(norm_header(a), canon)
    return lookup


def map_columns(raw_columns, targets):
    """-> (mapping {raw col: canonical}, ignored raw columns)."""
    lookup = build_header_lookup(targets)
    mapping, used, ignored = {}, set(), []
    for raw in raw_columns:
        canon = lookup.get(norm_header(raw))
        if canon is not None and canon not in used:
            mapping[raw] = canon
            used.add(canon)
        else:
            if str(raw).strip() and not str(raw).startswith("Unnamed:"): ignored.append(str(raw))
    return mapping, ignored


def read_uploaded_file(uploaded_file, targets):
    """Read .csv / .xlsx / .xls. For workbooks with several sheets every sheet that has recognisable headers is read."""
    name = (getattr(uploaded_file, "name", "") or "").lower()
    if name.endswith(".csv"):
        data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try: return pd.read_csv(io.BytesIO(data), dtype=object, encoding=enc, sep=None, engine="python")
            except UnicodeDecodeError: continue
        raise ValueError("Could not read this CSV file (unknown text encoding).")
    sheets = pd.read_excel(uploaded_file, sheet_name=None, dtype=object)
    frames = []
    for _, sdf in sheets.items():
        if sdf is None or sdf.empty: continue
        mapping, _ = map_columns(list(sdf.columns), targets)
        if mapping: frames.append(sdf)
    if not frames: return list(sheets.values())[0] if sheets else pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def parse_pasted_text(text, targets):
    """Text copied from Excel (tab separated). If the first row is not a header row, the template column order is assumed.
    Returns (DataFrame, used_template_order: bool)."""
    text = (text or "").strip("\n\r")
    if not text.strip(): return pd.DataFrame(), False
    sep = "\t" if "\t" in text.splitlines()[0] or "\t" in text else (";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ",")
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=object, keep_default_na=False, skipinitialspace=False, engine="python")
    mapping, _ = map_columns(list(df.columns), targets)
    if mapping: return df, False
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=object, keep_default_na=False, header=None, engine="python")
    cols = [c for c in TEMPLATE_ORDER if c in targets]
    df = df.iloc[:, :len(cols)]
    df.columns = cols[:df.shape[1]]
    return df, True


def _match_option(value, options):
    """Case-insensitive match against a dropdown list -> (label or '', matched?)."""
    v = clean_text(value)
    if not v: return "", True
    for o in options:
        if o and o.strip().lower() == v.lower(): return o, True
    return v, False


def prepare_import(raw_df, targets, date_cols, status_options, default_status, other_options, existing_refs, skip_existing=True, existing_auto_titles=None):
    """Turn a raw table (from file / paste / typed) into clean rows plus a report.
    other_options: {'Category': [...], 'Method of tender': [...], 'ITC Team': [...]} used for case-insensitive tidy-up only
    (values that are not in the list are kept as typed, never dropped).
    existing_auto_titles: {title: ref} of tenders that were given an automatic N/A-n reference earlier, so that re-importing the same
    reference-less row is recognised as 'already exists' instead of being added again.
    Returns dict(rows, preview, counts, ignored)."""
    counts = dict(new=0, exists=0, repeated=0, auto_ref=0, blank=0, bad_dates=0, bad_budget=0, status_fixed=0)
    if raw_df is None or raw_df.empty:
        return dict(rows=[], preview=pd.DataFrame(), counts=counts, ignored=[])
    mapping, ignored = map_columns(list(raw_df.columns), targets)
    df = raw_df[list(mapping.keys())].rename(columns=mapping)
    existing = {str(r).strip() for r in existing_refs}
    seen, rows, preview = set(), [], []
    auto_n = 0
    valid_status = [s for s in status_options if s]

    for _, r in df.iterrows():
        vals = {c: r.get(c) for c in df.columns}
        if all(clean_text(v) == "" for v in vals.values()):
            counts["blank"] += 1
            continue
        row = {}
        for col in df.columns:
            v = vals[col]
            if col in date_cols:
                txt, ok = parse_date(v)
                if not ok: counts["bad_dates"] += 1
                row[col] = txt
            elif col == "Budget FRW":
                num, ok = parse_budget(v)
                if not ok: counts["bad_budget"] += 1
                row[col] = num
            else:
                row[col] = clean_text(v)
        ref = row.get("Tender reference number", "")
        if not ref:
            if not row.get("Title of the tender", ""):
                counts["blank"] += 1
                continue
            title_key = row.get("Title of the tender", "").strip()
            known = (existing_auto_titles or {}).get(title_key)
            if known:
                ref = known                      # same title as an earlier automatic-reference row -> same tender
            else:
                auto_n += 1
                candidate = f"N/A-{auto_n}"
                while candidate in existing or candidate in seen:
                    auto_n += 1
                    candidate = f"N/A-{auto_n}"
                ref = candidate
                counts["auto_ref"] += 1
        row["Tender reference number"] = ref

        st_val, matched = _match_option(row.get("Current status", ""), valid_status)
        if not st_val or not matched:
            if st_val and not matched: counts["status_fixed"] += 1
            st_val = default_status
        row["Current status"] = st_val
        for col, opts in (other_options or {}).items():
            if col in row and row[col]:
                row[col], _ = _match_option(row[col], opts)

        if ref in seen:
            result = "Repeated in file - skipped"; counts["repeated"] += 1
            keep = False
        elif ref in existing and skip_existing:
            result = "Already exists - skipped"; counts["exists"] += 1
            keep = False
        elif ref in existing:
            result = "Will update existing"; counts["exists"] += 1
            keep = True
        else:
            result = "New"; counts["new"] += 1
            keep = True
        seen.add(ref)
        if keep: rows.append(row)
        preview.append({"Result": result, **{c: row.get(c, "") for c in ["Tender reference number", "Title of the tender", "Current status", "Category", "ITC Team", "Budget FRW"] if c in row or c == "Tender reference number"}})
    return dict(rows=rows, preview=pd.DataFrame(preview), counts=counts, ignored=ignored)


def build_template_bytes(columns, help_text=None):
    """Excel template: sheet 'Tenders' with the headers only, plus a 'Column guide' sheet."""
    help_text = help_text or COLUMN_HELP
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame(columns=[c.strip() for c in columns]).to_excel(xw, sheet_name="Tenders", index=False)
        guide = pd.DataFrame({
            "Column": [c.strip() for c in columns],
            "Meaning": [help_text.get(c, "Date (YYYY-MM-DD or DD/MM/YYYY)" if "date" in c.lower() else "Optional.") for c in columns],
        })
        guide.to_excel(xw, sheet_name="Column guide", index=False)
        ws = xw.sheets["Tenders"]
        for i, c in enumerate(columns, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, min(40, len(c) + 4))
        g = xw.sheets["Column guide"]
        g.column_dimensions["A"].width = 44; g.column_dimensions["B"].width = 110
    return out.getvalue()
