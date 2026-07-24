import sqlite3
import pandas as pd
import os
from datetime import datetime

# Railway safe-storage fix
DB_FILE = os.getenv("DATABASE_PATH", "tender_tracker.db")

RENAME_MAP = {
    'tender_no': 'Tender No',
    'tender_ref': 'Tender reference number',
    'title': 'Title of the tender',
    'end_user': 'End user',
    'smt_date': 'SMT date/PP Planned date of publication',
    'reason': 'Reason of approval/for initiating tender',
    'method': 'Method of tender',
    'responsible_officer': 'Responsible officer',
    'itc': 'ITC',
    'itc_submitted_date': 'Submitted date to ITC for TD approval',
    'itc_comments': 'Comments from ITC',
    'status': 'Current status',
    'date_awarded': 'Date awarded'
}

def get_conn():
    db_dir = os.path.dirname(DB_FILE)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fiscal_year TEXT,
            tender_no TEXT,
            tender_ref TEXT,
            title TEXT,
            end_user TEXT,
            smt_date TEXT,
            reason TEXT,
            method TEXT,
            responsible_officer TEXT,
            itc TEXT,
            itc_submitted_date TEXT,
            itc_comments TEXT,
            status TEXT
        )
    ''')
    
    # Safely add the new columns to existing databases without dropping data
    for col in ["date_awarded TEXT", "is_deleted INTEGER DEFAULT 0", "deleted_by TEXT", "deleted_at TEXT"]:
        try:
            c.execute(f"ALTER TABLE tenders ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
            
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            message TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS fiscal_years (
            year TEXT PRIMARY KEY
        )
    ''')
    c.execute('INSERT OR IGNORE INTO fiscal_years (year) VALUES ("2025-2026")')
    conn.commit()
    conn.close()

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
        # Wrap in quotes to safely handle spaces and casing in SQLite
        c.execute(f'ALTER TABLE tenders ADD COLUMN "{col_name}" TEXT')
        conn.commit()
        log_action(f"🔧 Added custom column: '{col_name}'")
        return True
    except sqlite3.OperationalError:
        pass # Column might already exist
    finally:
        conn.close()
    return False

def migrate_pending_tenders(old_fy, new_fy):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tenders WHERE fiscal_year = ? AND (is_deleted = 0 OR is_deleted IS NULL) AND status NOT IN ('Awarded', 'Cancelled')", (old_fy,))
    rows = c.fetchall()
    
    if not rows:
        conn.close()
        return

    columns = [desc[0] for desc in c.description]
    
    for row in rows:
        row_dict = dict(zip(columns, row))
        row_dict['fiscal_year'] = new_fy
        row_dict['id'] = None # Forces SQLite to generate a new primary key
        
        cols = []
        vals = []
        placeholders = []
        for k, v in row_dict.items():
            if k != 'id':
                cols.append(f'"{k}"')
                vals.append(v)
                placeholders.append("?")
        
        query = f"INSERT INTO tenders ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        c.execute(query, vals)
        
    conn.commit()
    conn.close()
    log_action(f"🔄 Migrated {len(rows)} pending tenders from {old_fy} to {new_fy}")

def log_action(message):
    conn = get_conn()
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO logs (timestamp, message) VALUES (?, ?)", (timestamp, message))
    conn.commit()
    conn.close()

def get_logs():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT timestamp, message FROM logs ORDER BY id DESC LIMIT 100")
    data = c.fetchall()
    columns = [desc[0] for desc in c.description]
    conn.close()
    return pd.DataFrame(data, columns=columns)

def load_data(fiscal_year):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tenders WHERE fiscal_year = ? AND (is_deleted = 0 OR is_deleted IS NULL)", (fiscal_year,))
    data = c.fetchall()
    columns = [desc[0] for desc in c.description]
    conn.close()
    
    df = pd.DataFrame(data, columns=columns)
    df.rename(columns=RENAME_MAP, inplace=True)
    df.drop(columns=['is_deleted', 'deleted_by', 'deleted_at'], errors='ignore', inplace=True)
    return df

def get_deleted_tenders(fiscal_year):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tenders WHERE fiscal_year = ? AND is_deleted = 1", (fiscal_year,))
    data = c.fetchall()
    columns = [desc[0] for desc in c.description]
    conn.close()
    
    df = pd.DataFrame(data, columns=columns)
    if not df.empty:
        df.rename(columns={'tender_no': 'Tender No', 'tender_ref': 'Tender reference number', 'title': 'Title of the tender', 'deleted_by': 'Deleted By', 'deleted_at': 'Deleted At'}, inplace=True)
    return df

def delete_tender(db_id, user_name):
    conn = get_conn()
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE tenders SET is_deleted = 1, deleted_by = ?, deleted_at = ? WHERE id = ?", (user_name, timestamp, db_id))
    conn.commit()
    conn.close()
    log_action(f"🗑️ Tender ID {db_id} deleted by {user_name}")

def upsert_tender(row_data):
    conn = get_conn()
    c = conn.cursor()
    
    c.execute('''
        SELECT id FROM tenders WHERE tender_ref = ? AND fiscal_year = ?
    ''', (row_data.get('Tender reference number', ''), row_data['fiscal_year']))
    existing = c.fetchone()
    
    if existing:
        c.execute('''
            UPDATE tenders SET 
                tender_no = ?, title = ?, end_user = ?, smt_date = ?, reason = ?, 
                method = ?, responsible_officer = ?, itc = ?, itc_submitted_date = ?, 
                itc_comments = ?, status = ?, date_awarded = ?, is_deleted = 0, deleted_by = NULL, deleted_at = NULL
            WHERE id = ?
        ''', (
            row_data.get('Tender No', ''), row_data.get('Title of the tender', ''), row_data.get('End user', ''),
            row_data.get('SMT date/PP Planned date of publication', ''), row_data.get('Reason of approval/for initiating tender', ''),
            row_data.get('Method of tender', ''), row_data.get('Responsible officer', ''), row_data.get('ITC', ''),
            row_data.get('Submitted date to ITC for TD approval', ''), row_data.get('Comments from ITC', ''),
            row_data.get('Current status', ''), row_data.get('Date awarded', ''), existing[0]
        ))
    else:
        c.execute('''
            INSERT INTO tenders (
                fiscal_year, tender_no, tender_ref, title, end_user, smt_date, reason,
                method, responsible_officer, itc, itc_submitted_date, itc_comments, status, date_awarded, is_deleted
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ''', (
            row_data['fiscal_year'], row_data.get('Tender No', ''), row_data.get('Tender reference number', ''),
            row_data.get('Title of the tender', ''), row_data.get('End user', ''), row_data.get('SMT date/PP Planned date of publication', ''),
            row_data.get('Reason of approval/for initiating tender', ''), row_data.get('Method of tender', ''),
            row_data.get('Responsible officer', ''), row_data.get('ITC', ''), row_data.get('Submitted date to ITC for TD approval', ''),
            row_data.get('Comments from ITC', ''), row_data.get('Current status', 'Planned'), row_data.get('Date awarded', '')
        ))
    conn.commit()
    conn.close()

def upsert_tenders_bulk(rows_data):
    # Truncated for brevity - handles standard CSV columns like the previous iteration.
    conn = get_conn()
    c = conn.cursor()
    for row_data in rows_data:
        c.execute('SELECT id FROM tenders WHERE tender_ref = ? AND fiscal_year = ?', (row_data.get('Tender reference number', ''), row_data['fiscal_year']))
        existing = c.fetchone()
        if existing:
            c.execute('''UPDATE tenders SET tender_no = ?, title = ?, end_user = ?, smt_date = ?, reason = ?, method = ?, responsible_officer = ?, itc = ?, itc_submitted_date = ?, itc_comments = ?, status = ?, date_awarded = ?, is_deleted = 0, deleted_by = NULL, deleted_at = NULL WHERE id = ?''', (row_data.get('Tender No', ''), row_data.get('Title of the tender', ''), row_data.get('End user', ''), row_data.get('SMT date/PP Planned date of publication', ''), row_data.get('Reason of approval/for initiating tender', ''), row_data.get('Method of tender', ''), row_data.get('Responsible officer', ''), row_data.get('ITC', ''), row_data.get('Submitted date to ITC for TD approval', ''), row_data.get('Comments from ITC', ''), row_data.get('Current status', ''), row_data.get('Date awarded', ''), existing[0]))
        else:
            c.execute('''INSERT INTO tenders (fiscal_year, tender_no, tender_ref, title, end_user, smt_date, reason, method, responsible_officer, itc, itc_submitted_date, itc_comments, status, date_awarded, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)''', (row_data['fiscal_year'], row_data.get('Tender No', ''), row_data.get('Tender reference number', ''), row_data.get('Title of the tender', ''), row_data.get('End user', ''), row_data.get('SMT date/PP Planned date of publication', ''), row_data.get('Reason of approval/for initiating tender', ''), row_data.get('Method of tender', ''), row_data.get('Responsible officer', ''), row_data.get('ITC', ''), row_data.get('Submitted date to ITC for TD approval', ''), row_data.get('Comments from ITC', ''), row_data.get('Current status', 'Planned'), row_data.get('Date awarded', '')))
    conn.commit()
    conn.close()

def update_single_cell(db_id, db_col_name, new_val):
    conn = get_conn()
    c = conn.cursor()
    query = f'UPDATE tenders SET "{db_col_name}" = ? WHERE id = ?'
    c.execute(query, (str(new_val), db_id))
    conn.commit()
    conn.close()