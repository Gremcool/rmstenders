import sqlite3
import pandas as pd
import os
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

def get_conn():
    db_dir = os.path.dirname(DB_FILE)
    if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir, exist_ok=True)
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def get_rename_map():
    conn = get_conn()
    c = conn.cursor()
    c.execute("PRAGMA table_info(tenders)")
    columns = [row[1] for row in c.fetchall()]
    conn.close()
    current_map = RENAME_MAP.copy()
    for col in columns:
        if col not in current_map and col not in ['id', 'is_deleted', 'deleted_by', 'deleted_at', 'fiscal_year']:
            current_map[col] = col
    return current_map

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fiscal_year TEXT, sn TEXT, tender_ref TEXT, title TEXT, category TEXT, smt_date TEXT,
            nature TEXT, method TEXT, end_user TEXT, budget REAL DEFAULT 0.0, source_of_funds TEXT, itc TEXT, responsible_officer TEXT, planned_pub_date TEXT, itc_submitted_date TEXT,
            itc_feedback_date TEXT, actual_pub_date TEXT, planned_bid_open_date TEXT, actual_bid_open_date TEXT, bids_to_itc_date TEXT, itc_eval_report_date TEXT, planned_prov_notif_date TEXT, actual_prov_notif_date TEXT,
            planned_contract_date TEXT, actual_contract_date TEXT, comments TEXT, status TEXT, is_deleted INTEGER DEFAULT 0, deleted_by TEXT, deleted_at TEXT
        )''')
    
    # --- EXPLICIT SCHEMA MIGRATION ---
    c.execute("PRAGMA table_info(tenders)")
    existing_cols = [row[1] for row in c.fetchall()]
    
    if 'budget' not in existing_cols:
        c.execute("ALTER TABLE tenders ADD COLUMN budget REAL DEFAULT 0.0")
    if 'source_of_funds' not in existing_cols:
        c.execute("ALTER TABLE tenders ADD COLUMN source_of_funds TEXT")
        
    c.execute('''CREATE TABLE IF NOT EXISTS dropdowns (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, label TEXT, color TEXT)''')
    
    c.execute("SELECT count(*) FROM dropdowns")
    if c.fetchone()[0] == 0:
        defaults = [
            ('status', 'Planned', '#6c757d'), ('status', 'Draft', '#adb5bd'), ('status', 'Published', '#17a2b8'),
            ('status', 'Under Evaluation', '#ffc107'), ('status', 'Awarded', '#28a745'), ('status', 'Cancelled', '#dc3545'),
            ('itc', 'ITC1', '#e3f2fd'), ('itc', 'ITC2', '#e3f2fd'), ('itc', 'ITC3', '#e3f2fd'), ('itc', 'ITC4', '#e3f2fd'),
            ('method', 'NCB', '#ffffff'), ('method', 'ICB', '#ffffff'), ('method', 'RFQ', '#ffffff'), 
            ('method', 'Direct Procurement', '#ffffff'), ('method', 'Framework', '#ffffff'), ('method', 'Other', '#ffffff')
        ]
        c.executemany("INSERT INTO dropdowns (category, label, color) VALUES (?, ?, ?)", defaults)

    c.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, message TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS fiscal_years (year TEXT PRIMARY KEY)')
    c.execute('INSERT OR IGNORE INTO fiscal_years (year) VALUES ("2025-2026")')
    conn.commit()
    conn.close()

# --- DROPDOWN MANAGEMENT ---
def get_dropdowns(category):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, label, color FROM dropdowns WHERE category = ? ORDER BY label", (category,))
    data = [{'id': row[0], 'label': row[1], 'color': row[2]} for row in c.fetchall()]
    conn.close()
    return data

def add_dropdown(category, label, color):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO dropdowns (category, label, color) VALUES (?, ?, ?)", (category, label, color))
    conn.commit()
    conn.close()

def update_dropdown(db_id, new_label, new_color):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE dropdowns SET label = ?, color = ? WHERE id = ?", (new_label, new_color, db_id))
    conn.commit()
    conn.close()

def delete_dropdown(db_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM dropdowns WHERE id = ?", (db_id,))
    conn.commit()
    conn.close()

# --- EXISTING DB FUNCTIONS ---
def get_fiscal_years():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT year FROM fiscal_years ORDER BY year DESC")
    years = [row[0] for row in c.fetchall()]
    conn.close()
    return years

def add_fiscal_year(year):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO fiscal_years (year) VALUES (?)', (year,))
    conn.commit()
    conn.close()
    log_action(f"📅 Created new Fiscal Year: {year}")

def add_custom_column(col_name):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(f'ALTER TABLE tenders ADD COLUMN "{col_name}" TEXT')
        conn.commit()
        log_action(f"🔧 Added custom column: '{col_name}'")
        return True
    except sqlite3.OperationalError: pass
    finally: conn.close()
    return False

def migrate_pending_tenders(old_fy, new_fy):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tenders WHERE fiscal_year = ? AND (is_deleted = 0 OR is_deleted IS NULL) AND status NOT IN ('Awarded', 'Cancelled')", (old_fy,))
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
    log_action(f"🔄 Migrated {len(rows)} pending tenders from {old_fy} to {new_fy}")

def log_action(message):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO logs (timestamp, message) VALUES (?, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))
    conn.commit()
    conn.close()

def get_logs():
    conn = get_conn()
    df = pd.read_sql("SELECT timestamp, message FROM logs ORDER BY id DESC LIMIT 100", conn)
    conn.close()
    return df

def load_data(fiscal_year):
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM tenders WHERE fiscal_year = ? AND (is_deleted = 0 OR is_deleted IS NULL)", conn, params=(fiscal_year,))
    conn.close()
    df.rename(columns=get_rename_map(), inplace=True)
    df.drop(columns=['is_deleted', 'deleted_by', 'deleted_at'], errors='ignore', inplace=True)
    return df

def get_deleted_tenders(fiscal_year):
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM tenders WHERE fiscal_year = ? AND is_deleted = 1", conn, params=(fiscal_year,))
    conn.close()
    if not df.empty:
        df.rename(columns=get_rename_map(), inplace=True)
        df.rename(columns={'deleted_by': 'Deleted By', 'deleted_at': 'Deleted At'}, inplace=True)
    return df

def delete_tender(db_id, user_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE tenders SET is_deleted = 1, deleted_by = ?, deleted_at = ? WHERE id = ?", (user_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), db_id))
    conn.commit()
    conn.close()
    log_action(f"🗑️ Tender ID {db_id} deleted by {user_name}")

def upsert_tenders_bulk(rows_data):
    conn = get_conn()
    c = conn.cursor()
    reverse_map = {v: k for k, v in get_rename_map().items()}
    for row_data in rows_data:
        db_row = {'fiscal_year': row_data['fiscal_year'], 'is_deleted': 0}
        for ui_col, val in row_data.items():
            if ui_col in reverse_map: db_row[reverse_map[ui_col]] = val
        c.execute('SELECT id FROM tenders WHERE tender_ref = ? AND fiscal_year = ?', (db_row.get('tender_ref', ''), db_row['fiscal_year']))
        existing = c.fetchone()
        cols = list(db_row.keys())
        vals = [db_row[k] for k in cols]
        if existing:
            set_clause = ", ".join([f'"{col}" = ?' for col in cols])
            vals.append(existing[0])
            c.execute(f"UPDATE tenders SET {set_clause} WHERE id = ?", vals)
        else:
            c.execute(f"INSERT INTO tenders ({', '.join([f'\"{col}\"' for col in cols])}) VALUES ({', '.join(['?'] * len(cols))})", vals)
    conn.commit()
    conn.close()

def upsert_tender(row_data):
    upsert_tenders_bulk([row_data])

def update_single_cell(db_id, db_col_name, new_val):
    conn = get_conn()
    c = conn.cursor()
    c.execute(f'UPDATE tenders SET "{db_col_name}" = ? WHERE id = ?', (str(new_val), db_id))
    conn.commit()
    conn.close()