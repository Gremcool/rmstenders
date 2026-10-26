import sqlite3
import pandas as pd
import os
import time
import threading
from contextlib import contextmanager
from datetime import datetime

DB_FILE = os.getenv("DATABASE_PATH", "tender_tracker.db")

RENAME_MAP = {
    'sn': 'S/N', 'tender_ref': 'Tender reference number', 'title': 'Title of the tender',
    'category': 'Category', 'smt_date': 'SMT date', 'nature': 'Nature (Goods, NC, etc)',
    'method': 'Method of tender', 'end_user': 'End users', 'budget': 'Budget FRW',
    'source_of_funds': 'Source of funds', 'itc': 'ITC Team', 'responsible_officer': 'Responsible officer',
    'planned_pub_date': 'Planned Publication date', 'itc_submitted_date': 'Submitted date to ITC for TD approval',
    'itc_feedback_date': 'Feedback from ITC on TD (date)', 'actual_pub_date': 'Actual Publication date',
    'planned_bid_open_date': 'Planned Bid opening date', 'actual_bid_open_date': 'Actual Bid Opening date',
    'bids_to_itc_date': 'Date bids are submitted for ITC evaluation', 'itc_eval_report_date': 'Date evaluation report is released from ITC',
    'planned_prov_notif_date': 'Planned Provisional Notification date', 'actual_prov_notif_date': 'Actual provisional Notification date ',
    'planned_contract_date': 'Planned Contract signing date', 'actual_contract_date': 'Actual contract date',
    'comments': 'Comments ', 'status': 'Current status'
}

SYSTEM_COLS = ['id', 'is_deleted', 'deleted_by', 'deleted_at', 'deleted_email', 'fiscal_year']

# Statuses that mean a tender is finished (used when carrying pending tenders into a new fiscal year)
CLOSED_STATUSES = ('Awarded', 'Cancelled', 'Completed')

# ---------------------------------------------------------------------------
# Tiny in-process read cache.
#  * Every write calls _invalidate(), so the app always sees its own changes.
#  * The key also contains the database file's mtime/size, so changes made by
#    anything else (another process, a restored backup) are noticed too.
# ---------------------------------------------------------------------------
_MISS = object()
_cache = {}
_cache_lock = threading.Lock()
_CACHE_MAX_ENTRIES = 200


def _stamp():
    parts = []
    for p in (DB_FILE, DB_FILE + "-wal"):
        try:
            s = os.stat(p)
            parts.append((s.st_mtime_ns, s.st_size))
        except OSError:
            parts.append(None)
    return tuple(parts)


def _cache_get(key):
    full = (key, _stamp())
    with _cache_lock:
        return _cache.get(full, _MISS)


def _cache_put(key, value):
    full = (key, _stamp())
    with _cache_lock:
        if len(_cache) > _CACHE_MAX_ENTRIES:
            _cache.clear()
        _cache[full] = value
    return value


def _invalidate():
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def get_conn():
    db_dir = os.path.dirname(DB_FILE)
    if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir, exist_ok=True)
    return sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)


@contextmanager
def _session(write=False):
    conn = get_conn()
    try:
        yield conn
        if write: conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _table_columns(conn):
    return [row[1] for row in conn.execute("PRAGMA table_info(tenders)").fetchall()]


def get_rename_map():
    cached = _cache_get('rename_map')
    if cached is not _MISS: return dict(cached)
    with _session() as conn:
        columns = _table_columns(conn)
    current_map = RENAME_MAP.copy()
    for col in columns:
        if col not in current_map and col not in SYSTEM_COLS:
            current_map[col] = col
    _cache_put('rename_map', current_map)
    return dict(current_map)


# ---------------------------------------------------------------------------
# Backups (never touches live data - it only reads and writes a copy)
# ---------------------------------------------------------------------------
def backup_db(tag="manual", keep=10):
    """Copy the live database to <db folder>/backups/ using SQLite's online backup API.
    Returns the backup path, or None if there is nothing to back up."""
    if not os.path.exists(DB_FILE): return None
    bdir = os.path.join(os.path.dirname(os.path.abspath(DB_FILE)), "backups")
    os.makedirs(bdir, exist_ok=True)
    base = os.path.basename(DB_FILE)
    path = os.path.join(bdir, f"{base}.{tag}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    src = sqlite3.connect(DB_FILE, timeout=30)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    # keep only the newest `keep` files for this tag (migration backups are kept forever)
    if tag != "pre-migration":
        prefix = f"{base}.{tag}."
        old = sorted([f for f in os.listdir(bdir) if f.startswith(prefix) and f.endswith(".bak")])
        for f in old[:-keep] if keep else []:
            try: os.remove(os.path.join(bdir, f))
            except OSError: pass
    return path


def get_backup_bytes():
    """A consistent snapshot of the whole database, for the 'download backup' button."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".db"); os.close(fd)
    src = sqlite3.connect(DB_FILE, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    try:
        with open(tmp, "rb") as fh: return fh.read()
    finally:
        try: os.remove(tmp)
        except OSError: pass


# ---------------------------------------------------------------------------
# Schema / migrations
# ---------------------------------------------------------------------------
_CANONICAL_COLUMNS = {
    'fiscal_year': 'TEXT', 'sn': 'TEXT', 'tender_ref': 'TEXT', 'title': 'TEXT', 'category': 'TEXT', 'smt_date': 'TEXT',
    'nature': 'TEXT', 'method': 'TEXT', 'end_user': 'TEXT', 'budget': 'REAL DEFAULT 0.0', 'source_of_funds': 'TEXT',
    'itc': 'TEXT', 'responsible_officer': 'TEXT', 'planned_pub_date': 'TEXT', 'itc_submitted_date': 'TEXT',
    'itc_feedback_date': 'TEXT', 'actual_pub_date': 'TEXT', 'planned_bid_open_date': 'TEXT', 'actual_bid_open_date': 'TEXT',
    'bids_to_itc_date': 'TEXT', 'itc_eval_report_date': 'TEXT', 'planned_prov_notif_date': 'TEXT',
    'actual_prov_notif_date': 'TEXT', 'planned_contract_date': 'TEXT', 'actual_contract_date': 'TEXT',
    'comments': 'TEXT', 'status': 'TEXT', 'is_deleted': 'INTEGER DEFAULT 0', 'deleted_by': 'TEXT', 'deleted_at': 'TEXT', 'deleted_email': 'TEXT',
}

_DEFAULT_DROPDOWNS = [
    ('status', 'Planned', '#6c757d'), ('status', 'Published', '#17a2b8'),
    ('status', 'Under Evaluation', '#ffc107'), ('status', 'Awarded', '#28a745'),
    ('status', 'Cancelled', '#dc3545'), ('status', 'Completed', '#6f42c1'),
    ('itc', 'ITC1', '#e3f2fd'), ('itc', 'ITC2', '#e3f2fd'), ('itc', 'ITC3', '#e3f2fd'), ('itc', 'ITC4', '#e3f2fd'),
    ('method', 'NCB', '#ffffff'), ('method', 'ICB', '#ffffff'), ('method', 'RFQ', '#ffffff'),
    ('method', 'Direct Procurement', '#ffffff'), ('method', 'Framework', '#ffffff'), ('method', 'Other', '#ffffff')
]

_MIG_STATUS_V1 = "status_remove_draft_add_cancelled_completed_v1"


def _log(conn, message):
    conn.execute("INSERT INTO logs (timestamp, message) VALUES (?, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))


def _migrate_statuses_v1(conn):
    """One-time: remove 'Draft', make sure 'Cancelled' and 'Completed' exist.
    Tenders that were 'Draft' become 'Planned' (nothing is deleted) and the change is written to the Edit Trail.
    Runs once only, so if you ever re-add 'Draft' yourself in Settings it will not be removed again."""
    c = conn.cursor()
    if c.execute("SELECT 1 FROM schema_migrations WHERE name = ?", (_MIG_STATUS_V1,)).fetchone(): return
    draft_rows = c.execute("SELECT id, tender_ref FROM tenders WHERE LOWER(TRIM(status)) = 'draft'").fetchall()
    labels = [r[0] for r in c.execute("SELECT label FROM dropdowns WHERE category = 'status'").fetchall()]
    has_draft_option = any(str(l).strip().lower() == 'draft' for l in labels)
    low = {str(l).strip().lower() for l in labels}
    missing = [(l, col) for l, col in (('Cancelled', '#dc3545'), ('Completed', '#6f42c1')) if l.lower() not in low]
    if draft_rows or has_draft_option or missing:
        conn.commit()
        try: backup_db("pre-migration")      # safety copy before anything is changed
        except Exception: pass
    if draft_rows:
        c.execute("UPDATE tenders SET status = 'Planned' WHERE LOWER(TRIM(status)) = 'draft'")
        refs = ", ".join(f"#{r[0]}:{r[1] or '(no ref)'}" for r in draft_rows[:60])
        more = f" ... and {len(draft_rows) - 60} more" if len(draft_rows) > 60 else ""
        _log(conn, f"🔁 Status update: 'Draft' was removed. {len(draft_rows)} tender(s) moved from Draft to Planned (id:ref) -> {refs}{more}")
    if has_draft_option:
        c.execute("DELETE FROM dropdowns WHERE category = 'status' AND LOWER(TRIM(label)) = 'draft'")
    for label, color in missing:
        c.execute("INSERT INTO dropdowns (category, label, color) VALUES ('status', ?, ?)", (label, color))
    if has_draft_option or missing:
        _log(conn, "🔧 Status options updated: removed 'Draft'; ensured 'Cancelled' and 'Completed' are available")
    c.execute("INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)", (_MIG_STATUS_V1, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()


_initialized_for = None


def init_db(force=False):
    global _initialized_for
    if _initialized_for == DB_FILE and not force: return   # schema only needs checking once per server start
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fiscal_year TEXT, sn TEXT, tender_ref TEXT, title TEXT, category TEXT, smt_date TEXT,
            nature TEXT, method TEXT, end_user TEXT, budget REAL DEFAULT 0.0, source_of_funds TEXT, itc TEXT, responsible_officer TEXT, planned_pub_date TEXT, itc_submitted_date TEXT,
            itc_feedback_date TEXT, actual_pub_date TEXT, planned_bid_open_date TEXT, actual_bid_open_date TEXT, bids_to_itc_date TEXT, itc_eval_report_date TEXT, planned_prov_notif_date TEXT, actual_prov_notif_date TEXT,
            planned_contract_date TEXT, actual_contract_date TEXT, comments TEXT, status TEXT, is_deleted INTEGER DEFAULT 0, deleted_by TEXT, deleted_at TEXT
        )''')

    # --- SAFE SCHEMA MIGRATION (only ever ADDS missing columns, never drops or rewrites) ---
    existing_cols = _table_columns(conn)
    for col, ddl in _CANONICAL_COLUMNS.items():
        if col not in existing_cols:
            c.execute(f'ALTER TABLE tenders ADD COLUMN "{col}" {ddl}')

    c.execute('''CREATE TABLE IF NOT EXISTS dropdowns (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, label TEXT, color TEXT)''')
    c.execute("SELECT count(*) FROM dropdowns")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO dropdowns (category, label, color) VALUES (?, ?, ?)", _DEFAULT_DROPDOWNS)

    c.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, message TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS fiscal_years (year TEXT PRIMARY KEY)')
    c.execute('INSERT OR IGNORE INTO fiscal_years (year) VALUES (?)', ("2025-2026",))
    c.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)')

    # --- INDEXES (speed only; no data change) ---
    for ddl in ("CREATE INDEX IF NOT EXISTS idx_tenders_fy ON tenders (fiscal_year)",
                "CREATE INDEX IF NOT EXISTS idx_tenders_fy_ref ON tenders (fiscal_year, tender_ref)",
                "CREATE INDEX IF NOT EXISTS idx_dropdowns_cat ON dropdowns (category)"):
        try: c.execute(ddl)
        except sqlite3.OperationalError: pass
    conn.commit()

    _migrate_statuses_v1(conn)
    conn.close()
    _invalidate()
    _initialized_for = DB_FILE


# --- DROPDOWN MANAGEMENT ---
def get_dropdowns(category):
    cached = _cache_get(('dropdowns', category))
    if cached is not _MISS: return [dict(x) for x in cached]
    with _session() as conn:
        rows = conn.execute("SELECT id, label, color FROM dropdowns WHERE category = ? ORDER BY label", (category,)).fetchall()
    data = [{'id': row[0], 'label': row[1], 'color': row[2]} for row in rows]
    _cache_put(('dropdowns', category), data)
    return [dict(x) for x in data]


def add_dropdown(category, label, color):
    with _session(write=True) as conn:
        conn.execute("INSERT INTO dropdowns (category, label, color) VALUES (?, ?, ?)", (category, label, color))
    _invalidate()


def update_dropdown(db_id, new_label, new_color):
    with _session(write=True) as conn:
        conn.execute("UPDATE dropdowns SET label = ?, color = ? WHERE id = ?", (new_label, new_color, db_id))
    _invalidate()


def delete_dropdown(db_id):
    with _session(write=True) as conn:
        conn.execute("DELETE FROM dropdowns WHERE id = ?", (db_id,))
    _invalidate()


# --- EXISTING DB FUNCTIONS ---
def get_fiscal_years():
    cached = _cache_get('fiscal_years')
    if cached is not _MISS: return list(cached)
    with _session() as conn:
        years = [row[0] for row in conn.execute("SELECT year FROM fiscal_years ORDER BY year DESC").fetchall()]
    _cache_put('fiscal_years', years)
    return list(years)


def add_fiscal_year(year):
    with _session(write=True) as conn:
        conn.execute('INSERT OR IGNORE INTO fiscal_years (year) VALUES (?)', (year,))
    _invalidate()
    log_action(f"📅 Created new Fiscal Year: {year}")


def add_custom_column(col_name):
    conn = get_conn()
    try:
        conn.execute(f'ALTER TABLE tenders ADD COLUMN "{col_name}" TEXT')
        conn.commit()
        _invalidate()
        log_action(f"🔧 Added custom column: '{col_name}'")
        return True
    except sqlite3.OperationalError: pass
    finally: conn.close()
    return False


def migrate_pending_tenders(old_fy, new_fy):
    conn = get_conn()
    c = conn.cursor()
    placeholders_closed = ", ".join("?" for _ in CLOSED_STATUSES)
    c.execute(f"SELECT * FROM tenders WHERE fiscal_year = ? AND (is_deleted = 0 OR is_deleted IS NULL) AND status NOT IN ({placeholders_closed})", (old_fy, *CLOSED_STATUSES))
    rows = c.fetchall()
    if not rows: return conn.close()
    columns = [desc[0] for desc in c.description]
    for row in rows:
        row_dict = dict(zip(columns, row))
        row_dict['fiscal_year'] = new_fy
        row_dict['id'] = None
        cols, vals, placeholders = [], [], []
        for k, v in row_dict.items():
            if k != 'id':
                cols.append(f'"{k}"'); vals.append(v); placeholders.append("?")
        c.execute(f"INSERT INTO tenders ({', '.join(cols)}) VALUES ({', '.join(placeholders)})", vals)
    conn.commit()
    conn.close()
    _invalidate()
    log_action(f"🔄 Migrated {len(rows)} pending tenders from {old_fy} to {new_fy}")


def log_action(message):
    with _session(write=True) as conn:
        _log(conn, message)


def get_logs():
    with _session() as conn:
        return pd.read_sql("SELECT timestamp, message FROM logs ORDER BY id DESC LIMIT 100", conn)


def load_data(fiscal_year):
    cached = _cache_get(('load_data', fiscal_year))
    if cached is not _MISS: return cached.copy()
    with _session() as conn:
        df = pd.read_sql("SELECT * FROM tenders WHERE fiscal_year = ? AND (is_deleted = 0 OR is_deleted IS NULL)", conn, params=(fiscal_year,))
    df.rename(columns=get_rename_map(), inplace=True)
    df.drop(columns=['is_deleted', 'deleted_by', 'deleted_at', 'deleted_email'], errors='ignore', inplace=True)
    _cache_put(('load_data', fiscal_year), df)
    return df.copy()


def get_deleted_tenders(fiscal_year):
    cached = _cache_get(('deleted', fiscal_year))
    if cached is not _MISS: return cached.copy()
    with _session() as conn:
        df = pd.read_sql("SELECT * FROM tenders WHERE fiscal_year = ? AND is_deleted = 1", conn, params=(fiscal_year,))
    if not df.empty:
        df.rename(columns=get_rename_map(), inplace=True)
        df.rename(columns={'deleted_by': 'Deleted By', 'deleted_email': 'Deleted By (Email)', 'deleted_at': 'Deleted At'}, inplace=True)
    _cache_put(('deleted', fiscal_year), df)
    return df.copy()


def get_existing_refs(fiscal_year, include_deleted=True):
    """Set of tender reference numbers already stored for a fiscal year (stripped)."""
    q = "SELECT tender_ref FROM tenders WHERE fiscal_year = ?"
    if not include_deleted: q += " AND (is_deleted = 0 OR is_deleted IS NULL)"
    with _session() as conn:
        return {str(r[0]).strip() for r in conn.execute(q, (fiscal_year,)).fetchall() if r[0] is not None}


def get_auto_ref_titles(fiscal_year):
    """{title: ref} for live tenders that got an automatic 'N/A-n' reference (used to avoid re-adding them on re-import)."""
    with _session() as conn:
        rows = conn.execute("SELECT tender_ref, title FROM tenders WHERE fiscal_year = ? AND (is_deleted = 0 OR is_deleted IS NULL) AND tender_ref LIKE 'N/A-%' ORDER BY id", (fiscal_year,)).fetchall()
    out = {}
    for ref, title in rows:
        if title is not None and str(title).strip(): out.setdefault(str(title).strip(), ref)
    return out


def delete_tender(db_id, user_name, email=""):
    with _session(write=True) as conn:
        conn.execute("UPDATE tenders SET is_deleted = 1, deleted_by = ?, deleted_email = ?, deleted_at = ? WHERE id = ?", (user_name, email, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), db_id))
    _invalidate()
    log_action(f"🗑️ Tender ID {db_id} deleted by {user_name} ({email})" if email else f"🗑️ Tender ID {db_id} deleted by {user_name}")


def upsert_tenders_bulk(rows_data):
    if not rows_data: return
    reverse_map = {v: k for k, v in get_rename_map().items()}
    with _session(write=True) as conn:
        c = conn.cursor()
        # one lookup per fiscal year instead of one query per row (first id wins, like the old fetchone())
        lookup = {}
        for fy in {r['fiscal_year'] for r in rows_data}:
            d = {}
            for rid, ref in c.execute("SELECT id, tender_ref FROM tenders WHERE fiscal_year = ? ORDER BY id", (fy,)).fetchall():
                d.setdefault(ref if ref is not None else None, rid)
            lookup[fy] = d
        for row_data in rows_data:
            db_row = {'fiscal_year': row_data['fiscal_year'], 'is_deleted': 0}
            for ui_col, val in row_data.items():
                if ui_col in reverse_map: db_row[reverse_map[ui_col]] = val
            ref_key = db_row.get('tender_ref', '')
            existing_id = lookup[db_row['fiscal_year']].get(ref_key)
            cols = list(db_row.keys())
            vals = [db_row[k] for k in cols]
            if existing_id is not None:
                set_clause = ", ".join([f'"{col}" = ?' for col in cols])
                c.execute(f"UPDATE tenders SET {set_clause} WHERE id = ?", vals + [existing_id])
            else:
                c.execute(f"INSERT INTO tenders ({', '.join(chr(34) + col + chr(34) for col in cols)}) VALUES ({', '.join(['?'] * len(cols))})", vals)
                lookup[db_row['fiscal_year']][ref_key] = c.lastrowid
    _invalidate()


def upsert_tender(row_data):
    upsert_tenders_bulk([row_data])


def import_tenders(fiscal_year, rows_data, skip_existing=True):
    """Bulk add from the Upload tab, in ONE transaction (all rows are saved or none are).
    rows_data use the on-screen column names. Returns counts.
      skip_existing=True : a row whose reference already exists in the live tracker is left completely untouched.
      skip_existing=False: the existing tender is updated, but only with the cells the file actually filled in
                           (blank cells in the file never wipe existing data)."""
    reverse_map = {v: k for k, v in get_rename_map().items()}
    res = {'inserted': 0, 'updated': 0, 'skipped': 0}
    if not rows_data: return res
    with _session(write=True) as conn:
        c = conn.cursor()
        ids_by_ref, live_refs = {}, set()
        for rid, ref, deleted in c.execute("SELECT id, tender_ref, is_deleted FROM tenders WHERE fiscal_year = ? ORDER BY id", (fiscal_year,)).fetchall():
            key = str(ref).strip() if ref is not None else ''
            ids_by_ref.setdefault(key, rid)
            if not deleted: live_refs.add(key)
        for row in rows_data:
            ref = str(row.get('Tender reference number', '')).strip()
            db_row = {}
            for ui_col, val in row.items():
                if ui_col in reverse_map: db_row[reverse_map[ui_col]] = val
            db_row['tender_ref'] = ref
            if ref in live_refs:
                if skip_existing:
                    res['skipped'] += 1
                    continue
                upd = {k: v for k, v in db_row.items() if k != 'tender_ref' and v not in ('', None)}
                if upd:
                    c.execute(f"UPDATE tenders SET {', '.join(chr(34) + k + chr(34) + ' = ?' for k in upd)} WHERE id = ?", list(upd.values()) + [ids_by_ref[ref]])
                res['updated'] += 1
                continue
            db_row.update({'fiscal_year': fiscal_year, 'is_deleted': 0})
            cols = list(db_row.keys())
            vals = [db_row[k] for k in cols]
            if ref in ids_by_ref:   # matches a deleted record -> restore it with the file's data (same as the old importer)
                c.execute(f"UPDATE tenders SET {', '.join(chr(34) + k + chr(34) + ' = ?' for k in cols)} WHERE id = ?", vals + [ids_by_ref[ref]])
            else:
                c.execute(f"INSERT INTO tenders ({', '.join(chr(34) + k + chr(34) for k in cols)}) VALUES ({', '.join(['?'] * len(cols))})", vals)
                ids_by_ref[ref] = c.lastrowid
            live_refs.add(ref)
            res['inserted'] += 1
        if res['inserted'] or res['updated']:
            _log(conn, f"📥 Import into {fiscal_year}: {res['inserted']} added, {res['updated']} updated, {res['skipped']} skipped")
    _invalidate()
    return res


def update_cells_bulk(updates):
    """updates: iterable of (db_id, db_col_name, new_val). Saved in ONE transaction instead of one commit per cell."""
    updates = list(updates)
    if not updates: return 0
    with _session(write=True) as conn:
        valid = set(_table_columns(conn)) - {'id'}
        by_col = {}
        for db_id, col, val in updates:
            if col in valid: by_col.setdefault(col, []).append((str(val), int(db_id)))
        n = 0
        for col, params in by_col.items():
            conn.executemany(f'UPDATE tenders SET "{col}" = ? WHERE id = ?', params)
            n += len(params)
    _invalidate()
    return n


def update_single_cell(db_id, db_col_name, new_val):
    update_cells_bulk([(db_id, db_col_name, new_val)])
