import streamlit as st
import pandas as pd
import os
import re
import io
import time
import json
from datetime import datetime
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode, JsCode
from streamlit_quill import st_quill
import plotly.express as px
import db
import tracker_utils as tu

# --- SETTINGS ---

# --- PAGE CONFIG & CSS ---
st.set_page_config(page_title="RMS Tender Efficiency Tracker", layout="wide", initial_sidebar_state="collapsed")
db.init_db()

st.markdown("""
    <style>
        header {visibility: hidden;} #MainMenu {visibility: hidden;}
        [data-testid="stSidebar"] { display: none !important; }
        
        .block-container { padding-top: 0.5rem !important; padding-bottom: 0.5rem !important; background-color: #f4f7f6;}
        div[data-testid="stVerticalBlock"] > div { padding-bottom: 0.1rem !important; }
        div[data-testid="stForm"] { margin-bottom: 0px !important; }
        
        .top-banner {
            background: linear-gradient(90deg, #0275d8 0%, #0056b3 100%);
            padding: 4px 15px; border-radius: 6px; color: white;
            display: flex; align-items: center; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 5px;
        }
        .top-banner h1 { margin:0; font-weight: 800; font-size: 18px; color: white; letter-spacing: 0.5px;}
        .top-banner img { border-radius: 4px; margin-right: 15px; background: white; padding: 2px; }
        
        .eff-card {
            padding: 10px 15px; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); height: 75px;
            display: flex; flex-direction: column; justify-content: center; border: 1px solid #eee; margin-top: 5px; margin-bottom: 5px;
        }
        .eff-title { font-size: 10px; font-weight: 800; text-transform: uppercase; margin-bottom: 2px; color: #495057; }
        .eff-value { font-size: 22px; font-weight: 900; margin: 0; line-height: 1.1; }
        .eff-sub { font-size: 10px; color: #6c757d; margin-top: 2px; font-weight: 500; }
        
        .bg-green { background-color: #e8f5e9; border-left: 5px solid #28a745; }
        .bg-purple { background-color: #f3e5f5; border-left: 5px solid #6f42c1; }
        .bg-blue { background-color: #e3f2fd; border-left: 5px solid #007bff; }
        .bg-orange { background-color: #fff3cd; border-left: 5px solid #fd7e14; }
        .bg-dark { background-color: #17a2b8; border-left: 5px solid #117a8b; color: white !important;}
        .bg-dark .eff-title, .bg-dark .eff-sub { color: #e0f7fa !important; }
        
        div.stTabs { margin-top: -5px; }
        div[data-baseweb="tab-list"] { background-color: #e3f2fd !important; border-radius: 8px; padding: 5px 10px; gap: 5px; }
        div[data-baseweb="tab"] { background-color: transparent !important; border-radius: 6px !important; padding-top: 8px !important; padding-bottom: 8px !important; margin: 0px !important; }
        div[data-baseweb="tab"][aria-selected="true"] { background-color: #ffffff !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important; border: 1px solid #cce5ff !important; }
        
        .align-btn { display: flex; align-items: flex-end; height: 100%; padding-bottom: 2px;}
        iframe[title*="agGrid"] { max-height: calc(100vh - 60px); }
        .import-info { background-color: #e3f2fd; border-radius: 8px; padding: 14px 18px; color: #0b4a8f; font-size: 15px; line-height: 1.7; margin-bottom: 10px; }
        .import-info .req { color: #c62828; font-weight: 600; } .import-info .rec { color: #e65100; font-weight: 600; }
    </style>
""", unsafe_allow_html=True)

logo_html = ""
if os.path.exists("logo_2.jpg"):
    import base64
    with open("logo_2.jpg", "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode()
    logo_html = f"<img src='data:image/jpeg;base64,{encoded_string}' height='35'/>"

st.markdown(f"<div class='top-banner'>{logo_html}<h1>RMS Tender Efficiency & Process Tracker</h1></div>", unsafe_allow_html=True)

def create_kpi_card(title, value, bg_color, border_color, val_color):
    return f"""<div class='eff-card' style='background-color: {bg_color}; border-left: 5px solid {border_color};'>
        <div class='eff-title'>{title}</div>
        <div class='eff-value' style='color: {val_color};'>{value}</div>
        </div>"""

@st.cache_data(show_spinner=False, max_entries=32)
def fig_closure_chart(grouped, sla_days):
    fig = px.bar(grouped, y='ITC Team', x='avg_days', text='custom_text', color='ITC Team', orientation='h', color_discrete_sequence=px.colors.qualitative.Pastel)
    fig.update_traces(textposition='inside', insidetextfont=dict(color='#2c3e50', size=14, family="Arial Black"), marker_line_color='rgba(0,0,0,0.1)', marker_line_width=1)
    fig.update_layout(xaxis_title="Average Days to Close", yaxis_title="", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', height=300, margin=dict(l=0, r=0, t=20, b=0), showlegend=False)
    return fig

@st.cache_data(show_spinner=False, max_entries=32)
def fig_status_counts_chart(counts, x_col, x_title):
    fig = px.bar(counts, x=x_col, y='Count', color='Current status', text='Count')
    fig.update_layout(xaxis_title=x_title, yaxis_title="Total Tenders", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
    return fig

def bump_grid():
    """Make the grid reload fresh data on the next run. Without this the grid hands back its old on-screen values and the
    save-sync writes them over a change that was just saved from a dialog or an import."""
    st.session_state["grid_ver"] = st.session_state.get("grid_ver", 0) + 1

def opts_with_current(options, current):
    """Dropdown options plus the row's current value (if it is not in the list), so saving never silently erases it."""
    cur = "" if current is None or (isinstance(current, float) and pd.isna(current)) else str(current)
    return list(options) + ([cur] if cur and cur not in options else [])

def format_budget(val):
    try:
        val = float(val)
        if val >= 1_000_000_000: return f"{val/1_000_000_000:.2f}B FRW"
        elif val >= 1_000_000: return f"{val/1_000_000:.2f}M FRW"
        return f"{val:,.0f} FRW"
    except: return "0 FRW"

ALL_DATE_COLS = [
    'SMT date', 'Planned Publication date', 'Submitted date to ITC for TD approval', 'Feedback from ITC on TD (date)',
    'Actual Publication date', 'Planned Bid opening date', 'Actual Bid Opening date', 'Date bids are submitted for ITC evaluation',
    'Date evaluation report is released from ITC', 'Planned Provisional Notification date', 'Actual provisional Notification date ',
    'Planned Contract signing date', 'Actual contract date', 'Date awarded'
]

# --- LOAD DYNAMIC DROPDOWNS ---
db_status_opts = db.get_dropdowns('status')
db_itc_opts = db.get_dropdowns('itc')
db_method_opts = db.get_dropdowns('method')
db_cat_opts = db.get_dropdowns('category')

STATUS_OPTIONS = [""] + [opt['label'] for opt in db_status_opts]
ITC_OPTIONS = [""] + [opt['label'] for opt in db_itc_opts]
METHOD_OPTIONS = [""] + [opt['label'] for opt in db_method_opts]
CAT_OPTIONS = [""] + [opt['label'] for opt in db_cat_opts]

status_color_map = {opt['label']: opt['color'] for opt in db_status_opts}
itc_color_map = {opt['label']: opt['color'] for opt in db_itc_opts}
cat_color_map = {opt['label']: opt['color'] for opt in db_cat_opts}

@st.dialog("⚙️ Manage Dropdown Options", width="large")
def manage_dropdowns_dialog():
    st.markdown("Edit existing options or add new ones to the lists.")
    cat = st.selectbox("Select List to Edit", ["Current status", "ITC Team", "Method of tender", "Category"])
    db_cat_map = {"Current status": "status", "ITC Team": "itc", "Method of tender": "method", "Category": "category"}
    active_cat = db_cat_map[cat]
    
    options = db.get_dropdowns(active_cat)
    st.markdown("---")
    
    for opt in options:
        c1, c2, c3, c4 = st.columns([1, 4, 1.5, 1.5])
        with c1: new_c = st.color_picker("Color", opt['color'], key=f"c_{opt['id']}", label_visibility="collapsed")
        with c2: new_l = st.text_input("Label", opt['label'], key=f"l_{opt['id']}", label_visibility="collapsed")
        with c3:
            if st.button("💾 Update", key=f"save_{opt['id']}", use_container_width=True):
                db.update_dropdown(opt['id'], new_l.strip(), new_c)
                st.rerun()
        with c4: 
            if st.button("❌ Del", key=f"del_{opt['id']}", use_container_width=True):
                db.delete_dropdown(opt['id'])
                st.rerun()
                
    st.markdown("### ➕ Add New Option")
    nc1, nc2, nc3 = st.columns([1, 4, 3])
    with nc1: new_color = st.color_picker("Pick Color", "#ffffff", key="new_col")
    with nc2: new_label = st.text_input("Option Label", key="new_lab")
    with nc3: 
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Add Option", type="primary", use_container_width=True):
            if new_label:
                db.add_dropdown(active_cat, new_label.strip(), new_color)
                st.rerun()

# --- DIALOGS ---
@st.dialog("➕ Add New Tender", width="large")
def add_tender_dialog(active_fy):
    with st.form("add_tender_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            new_t_no = st.text_input("Tender No (S/N)")
            new_ref = st.text_input("Tender reference number *Required*")
            new_status = st.selectbox("Current status", STATUS_OPTIONS)
        with c2:
            new_cat = st.selectbox("Category", CAT_OPTIONS)
            new_method = st.selectbox("Method of tender", METHOD_OPTIONS)
        with c3:
            new_itc = st.selectbox("ITC Team", ITC_OPTIONS)
            new_officer = st.text_input("Responsible officer")
        with c4:
            new_budget = st.number_input("Budget FRW", value=0.0)
            new_source = st.text_input("Source of funds")

        st.markdown("### 📅 Dates")
        date_vals = {}
        date_chunks = [ALL_DATE_COLS[i:i+4] for i in range(0, len(ALL_DATE_COLS), 4)]
        for chunk in date_chunks:
            cols = st.columns(4)
            for i, col_name in enumerate(chunk):
                with cols[i]:
                    selected_d = st.date_input(col_name, value=None, key=f"d_{col_name}_new")
                    date_vals[col_name] = selected_d.strftime('%Y-%m-%d') if selected_d else ""

        st.divider()
        st.markdown("**Title of the tender**")
        new_title = st_quill(placeholder="Write title here...", html=True, key="q_t_new")
        st.markdown("**Comments**")
        new_com = st_quill(placeholder="Write comments here...", html=True, key="q_c_new")
        
        if st.form_submit_button("Save to Database", type="primary", use_container_width=True):
            if new_ref.strip() == "":
                st.error("⚠️ Tender reference number is required!")
            else:
                new_row = {
                    'fiscal_year': active_fy, 'S/N': new_t_no, 'Tender reference number': new_ref,
                    'Title of the tender': new_title, 'Category': new_cat, 'Method of tender': new_method, 
                    'Responsible officer': new_officer, 'ITC Team': new_itc, 'Budget FRW': new_budget, 
                    'Source of funds': new_source, 'Comments ': new_com, 'Current status': new_status
                }
                new_row.update(date_vals)
                db.upsert_tender(new_row)
                bump_grid()
                st.success("Tender Saved!")
                time.sleep(0.2)
                st.rerun()

@st.dialog("✏️ Edit Advanced Details", width="large")
def edit_row_dialog(row_data, active_fy):
    t_id = row_data.get('id', 'new')
    
    st_opts = opts_with_current(STATUS_OPTIONS, row_data.get("Current status"))
    me_opts = opts_with_current(METHOD_OPTIONS, row_data.get("Method of tender"))
    itc_opts = opts_with_current(ITC_OPTIONS, row_data.get("ITC Team"))
    cat_opts = opts_with_current(CAT_OPTIONS, row_data.get("Category"))
    status_idx = st_opts.index(row_data.get("Current status", "")) if row_data.get("Current status") in st_opts else 0
    method_idx = me_opts.index(row_data.get("Method of tender", "")) if row_data.get("Method of tender") in me_opts else 0
    itc_idx = itc_opts.index(row_data.get("ITC Team", "")) if row_data.get("ITC Team") in itc_opts else 0
    cat_idx = cat_opts.index(row_data.get("Category", "")) if row_data.get("Category") in cat_opts else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        new_t_no = st.text_input("Tender No (S/N)", value=row_data.get("S/N", ""))
        new_status = st.selectbox("Current status", st_opts, index=status_idx)
    with c2:
        new_cat = st.selectbox("Category", cat_opts, index=cat_idx)
        new_method = st.selectbox("Method of tender", me_opts, index=method_idx)
    with c3:
        new_itc = st.selectbox("ITC Team", itc_opts, index=itc_idx)
        new_officer = st.text_input("Responsible officer", value=row_data.get("Responsible officer", ""))
    with c4:
        try: def_budget = float(row_data.get('Budget FRW', 0))
        except: def_budget = 0.0
        new_budget = st.number_input("Budget FRW", value=def_budget)
        new_source = st.text_input("Source of funds", value=row_data.get('Source of funds', ''))

    st.markdown("### 📅 Dates")
    date_vals = {}
    date_chunks = [ALL_DATE_COLS[i:i+4] for i in range(0, len(ALL_DATE_COLS), 4)]
    for chunk in date_chunks:
        cols = st.columns(4)
        for i, col_name in enumerate(chunk):
            with cols[i]:
                raw_d = pd.to_datetime(row_data.get(col_name, ""), errors='coerce')
                def_d = raw_d.date() if pd.notna(raw_d) else None
                selected_d = st.date_input(col_name, value=def_d, key=f"d_{col_name}_{t_id}")
                date_vals[col_name] = selected_d.strftime('%Y-%m-%d') if selected_d else ""

    st.divider()
    def safe_str(val): return "" if pd.isna(val) else str(val)
    st.markdown("**Title of the tender**")
    new_title = st_quill(value=safe_str(row_data.get('Title of the tender')), html=True, key=f"q_t_{t_id}")
    st.markdown("**Comments**")
    new_com = st_quill(value=safe_str(row_data.get('Comments ')), html=True, key=f"q_c_{t_id}")
    
    if st.button("Save Changes", type="primary", use_container_width=True):
        updated_row = {
            'fiscal_year': active_fy, 'S/N': new_t_no, 'Tender reference number': row_data.get("Tender reference number", ""),
            'Title of the tender': new_title, 'Category': new_cat, 'Method of tender': new_method, 
            'Responsible officer': new_officer, 'ITC Team': new_itc, 'Budget FRW': new_budget, 
            'Source of funds': new_source, 'Comments ': new_com, 'Current status': new_status
        }
        updated_row.update(date_vals)
        db.upsert_tender(updated_row)
        bump_grid()
        st.success("Changes Saved!")
        time.sleep(0.2)
        st.rerun()

@st.dialog("📄 Duplicate Tender", width="large")
def duplicate_row_dialog(row_data, active_fy):
    """Copy the selected tender into one or more NEW rows. Only the reference number has to be different."""
    t_id = row_data.get('id', 'x')
    kp = f"dup_{t_id}"
    existing_refs = db.get_existing_refs(active_fy, include_deleted=True)
    src_ref = str(row_data.get("Tender reference number", "")).strip()

    # suggest a free reference: "<ref>-2", "<ref>-3", ...
    n = 2
    while f"{src_ref}-{n}" in existing_refs: n += 1
    suggested_ref = f"{src_ref}-{n}"

    # suggest the next S/N when the current ones are numbers
    sn_series = pd.to_numeric(db.load_data(active_fy).get('S/N', pd.Series(dtype=float)), errors='coerce')
    suggested_sn = str(int(sn_series.max()) + 1) if sn_series.notna().any() and pd.notna(pd.to_numeric(row_data.get("S/N", ""), errors='coerce')) else str(row_data.get("S/N", "") or "")

    st.caption(f"Copying everything from **{src_ref}**. Change whatever should be different, then save. Nothing is changed on the original tender.")

    st_opts = opts_with_current(STATUS_OPTIONS, row_data.get("Current status"))
    me_opts = opts_with_current(METHOD_OPTIONS, row_data.get("Method of tender"))
    itc_opts = opts_with_current(ITC_OPTIONS, row_data.get("ITC Team"))
    cat_opts = opts_with_current(CAT_OPTIONS, row_data.get("Category"))
    status_idx = st_opts.index(row_data.get("Current status", "")) if row_data.get("Current status") in st_opts else 0
    method_idx = me_opts.index(row_data.get("Method of tender", "")) if row_data.get("Method of tender") in me_opts else 0
    itc_idx = itc_opts.index(row_data.get("ITC Team", "")) if row_data.get("ITC Team") in itc_opts else 0
    cat_idx = cat_opts.index(row_data.get("Category", "")) if row_data.get("Category") in cat_opts else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        new_ref = st.text_input("New tender reference number *Required*", value=suggested_ref, key=f"{kp}_ref")
        new_t_no = st.text_input("Tender No (S/N)", value=suggested_sn, key=f"{kp}_sn")
        new_status = st.selectbox("Current status", st_opts, index=status_idx, key=f"{kp}_status")
    with c2:
        new_cat = st.selectbox("Category", cat_opts, index=cat_idx, key=f"{kp}_cat")
        new_method = st.selectbox("Method of tender", me_opts, index=method_idx, key=f"{kp}_method")
        copies = st.number_input("Number of copies", min_value=1, max_value=50, value=1, step=1, key=f"{kp}_n",
                                 help="With more than one copy, -1, -2, -3 ... is added to the reference number.")
    with c3:
        new_itc = st.selectbox("ITC Team", itc_opts, index=itc_idx, key=f"{kp}_itc")
        new_officer = st.text_input("Responsible officer", value=str(row_data.get("Responsible officer", "") or ""), key=f"{kp}_off")
    with c4:
        try: def_budget = float(row_data.get('Budget FRW', 0))
        except Exception: def_budget = 0.0
        new_budget = st.number_input("Budget FRW", value=def_budget, key=f"{kp}_bud")
        new_source = st.text_input("Source of funds", value=str(row_data.get('Source of funds', '') or ''), key=f"{kp}_src")

    copy_dates = st.checkbox("Also copy the dates", value=True, key=f"{kp}_dates", help="Untick to start the new row(s) with empty dates.")
    date_vals = {}
    if copy_dates:
        with st.expander("📅 Dates (copied - open to change)"):
            date_chunks = [ALL_DATE_COLS[i:i+4] for i in range(0, len(ALL_DATE_COLS), 4)]
            for chunk in date_chunks:
                cols = st.columns(4)
                for i, col_name in enumerate(chunk):
                    with cols[i]:
                        raw_d = pd.to_datetime(row_data.get(col_name, ""), errors='coerce')
                        def_d = raw_d.date() if pd.notna(raw_d) else None
                        selected_d = st.date_input(col_name, value=def_d, key=f"{kp}_d_{col_name}")
                        date_vals[col_name] = selected_d.strftime('%Y-%m-%d') if selected_d else ""
    else:
        date_vals = {col_name: "" for col_name in ALL_DATE_COLS}

    def safe_str(val): return "" if pd.isna(val) else str(val)
    st.divider()
    st.markdown("**Title of the tender**")
    new_title = st_quill(value=safe_str(row_data.get('Title of the tender')), html=True, key=f"{kp}_qt")
    st.markdown("**Comments**")
    new_com = st_quill(value=safe_str(row_data.get('Comments ')), html=True, key=f"{kp}_qc")

    if st.button("Save Copy", type="primary", use_container_width=True, key=f"{kp}_save"):
        base_ref = new_ref.strip()
        if base_ref == "":
            st.error("⚠️ Tender reference number is required!")
        else:
            refs = [base_ref] if int(copies) == 1 else [f"{base_ref}-{i}" for i in range(1, int(copies) + 1)]
            clash = [r for r in refs if r in existing_refs]
            if clash:
                st.error(f"⚠️ Reference number already exists: {', '.join(clash[:5])}. Please use a different one.")
            else:
                # carry over every other saved column too (incl. custom columns), then apply what was edited above
                editable = set(db.get_rename_map().values())
                base = {c: row_data[c] for c in editable if c in row_data and not (isinstance(row_data[c], float) and pd.isna(row_data[c]))}
                base.update({
                    'fiscal_year': active_fy, 'S/N': new_t_no, 'Title of the tender': new_title, 'Category': new_cat,
                    'Method of tender': new_method, 'Responsible officer': new_officer, 'ITC Team': new_itc, 'Budget FRW': new_budget,
                    'Source of funds': new_source, 'Comments ': new_com, 'Current status': new_status
                })
                base.update(date_vals)
                db.upsert_tenders_bulk([{**base, 'Tender reference number': r} for r in refs])
                db.log_action(f"📄 Duplicated tender '{src_ref}' -> {', '.join(refs[:5])}{' ...' if len(refs) > 5 else ''} ({len(refs)} new row(s))")
                bump_grid()
                st.success(f"Created {len(refs)} new row(s)!")
                time.sleep(0.2)
                st.rerun()

@st.dialog("🗑️ Confirm Deletion")
def delete_row_dialog(row_data):
    st.warning(f"Are you sure you want to delete Tender Ref: `{row_data.get('Tender reference number', 'N/A')}`?")
    user_name = st.text_input("Enter your name to confirm deletion:")
    user_email = st.text_input("Enter your email:")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancel", use_container_width=True): st.rerun()
    with c2:
        if st.button("Delete Permanently", type="primary", use_container_width=True):
            email = user_email.strip()
            if not user_name.strip(): st.error("⚠️ Your name is required.")
            elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email): st.error("⚠️ A valid email is required (e.g. name@rms.rw).")
            else:
                db.delete_tender(int(row_data['id']), user_name.strip(), email)
                bump_grid()
                st.rerun()

# --- FISCAL YEAR ---
fiscal_years = db.get_fiscal_years()
# Explicitly sort to ensure the latest year is always first in the list
fiscal_years = sorted(fiscal_years, reverse=True) if fiscal_years else ["2025-2026"]

col_fy1, col_fy2 = st.columns([1, 1])
with col_fy1: 
    selected_fy = st.selectbox("📂 Active Fiscal Year", fiscal_years, index=0, label_visibility="collapsed")
with col_fy2:
    with st.expander("➕ Initialize New Fiscal Year"):
        new_fy = st.text_input("Enter Year (e.g., 2026-2027)")
        if st.button("Create Year"):
            if new_fy and new_fy not in fiscal_years:
                db.add_fiscal_year(new_fy.strip())
                st.rerun()

tab_dash, tab_upload, tab_logs, tab_deleted = st.tabs(["📊 Tender Tracker & Analytics", "📂 Upload Data", "📝 Edit Trail", "🗑️ Deleted Records"])

with tab_dash:
    df = db.load_data(selected_fy)
    
    # --- FILTERS ---
    f0, f1, f2, f3 = st.columns(4)
    with f0: f_search = st.text_input("🔍 Search", placeholder="Ref, Title, S/N...")
    with f1: f_itc = st.multiselect("ITC Team", options=ITC_OPTIONS)
    with f2: f_status = st.multiselect("Current Status", options=STATUS_OPTIONS)
    with f3: f_cat = st.multiselect("Category", options=CAT_OPTIONS)

    f_df = df.copy()
    
    # Apply Search Filter
    if f_search:
        search_mask = (
            f_df['Tender reference number'].astype(str).str.contains(f_search, case=False, na=False) |
            f_df['Title of the tender'].astype(str).str.contains(f_search, case=False, na=False) |
            f_df.get('S/N', pd.Series(dtype=str)).astype(str).str.contains(f_search, case=False, na=False)
        )
        f_df = f_df[search_mask]
        
    if f_itc: f_df = f_df[f_df['ITC Team'].isin(f_itc)]
    if f_status: f_df = f_df[f_df['Current status'].isin(f_status)]
    if f_cat: f_df = f_df[f_df['Category'].isin(f_cat)]

    # --- ALIGNED ACTIONS ROW ---
    col_setting, col_add_btn, col_custom_col, col_config = st.columns([2, 2, 3, 4])
    with col_setting:
        sla_days = st.number_input("🚨 SLA Red-Line (Days)", min_value=1, value=21)
    with col_add_btn:
        st.markdown("<div class='align-btn'>", unsafe_allow_html=True)
        if st.button("➕ Add New Row", use_container_width=True, type="primary"):
            add_tender_dialog(selected_fy)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_custom_col:
        st.markdown("<div class='align-btn'>", unsafe_allow_html=True)
        with st.popover("➕ Add Custom Column", use_container_width=True):
            new_col_name = st.text_input("Column Name")
            if st.button("Add to Grid") and new_col_name:
                db.add_custom_column(new_col_name.strip())
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with col_config:
        st.markdown("<div class='align-btn'>", unsafe_allow_html=True)
        if st.button("⚙️ Settings (Colors & Dropdowns)", use_container_width=True): manage_dropdowns_dialog()
        st.markdown("</div>", unsafe_allow_html=True)

    # --- PRIMARY KPI MATH ---
    today_str = datetime.today().strftime('%Y-%m-%d')
    f_df['Sub_Date'] = pd.to_datetime(f_df.get('Submitted date to ITC for TD approval', ''), errors='coerce')
    f_df['Award_Date'] = pd.to_datetime(f_df.get('Date awarded', ''), errors='coerce')
    f_df['Calc_Award_Date'] = f_df['Award_Date'].fillna(pd.to_datetime(today_str))
    f_df['Days_to_Close'] = (f_df['Calc_Award_Date'] - f_df['Sub_Date']).dt.days

    active_mask = ~f_df.get('Current status', pd.Series()).isin(['Awarded', 'Cancelled', 'Completed', 'Planned'])
    f_df['Is_Overdue'] = (f_df['Days_to_Close'] > sla_days) & active_mask
    overdue_count = int(f_df['Is_Overdue'].sum()) if not f_df.empty else 0

    valid_tenders = f_df.dropna(subset=['Sub_Date']).copy()
    avg_days_to_close = int(valid_tenders['Days_to_Close'].mean()) if not valid_tenders.empty and not valid_tenders['Days_to_Close'].isna().all() else 0

    met1, met2, met3, met4, met5, met_c1, met_c2, met6, met7 = st.columns(9)
    with met1: st.markdown(create_kpi_card("Total Tenders", len(f_df), "#f8f9fa", "#adb5bd", "#2c3e50"), unsafe_allow_html=True)
    with met2: st.markdown(create_kpi_card("Awarded ✅", len(f_df[f_df.get("Current status") == "Awarded"]) if not f_df.empty else 0, "#e8f5e9", "#28a745", "#155724"), unsafe_allow_html=True)
    with met3: st.markdown(create_kpi_card("Evaluation 🔄", len(f_df[f_df.get("Current status") == "Under Evaluation"]) if not f_df.empty else 0, "#fff3cd", "#ffc107", "#856404"), unsafe_allow_html=True)
    with met4: st.markdown(create_kpi_card("Published 📢", len(f_df[f_df.get("Current status") == "Published"]) if not f_df.empty else 0, "#e3f2fd", "#007bff", "#004085"), unsafe_allow_html=True)
    with met5: st.markdown(create_kpi_card("Planned ⏳", len(f_df[f_df.get("Current status") == "Planned"]) if not f_df.empty else 0, "#e2e3e5", "#6c757d", "#383d41"), unsafe_allow_html=True)
    with met_c1: st.markdown(create_kpi_card("Cancelled ❌", len(f_df[f_df.get("Current status") == "Cancelled"]) if not f_df.empty else 0, "#fdecea", "#dc3545", "#842029"), unsafe_allow_html=True)
    with met_c2: st.markdown(create_kpi_card("Completed 🏁", len(f_df[f_df.get("Current status") == "Completed"]) if not f_df.empty else 0, "#ede7f6", "#6610f2", "#3d0a91"), unsafe_allow_html=True)
    with met6: st.markdown(create_kpi_card("Avg Days Close ⏱️", avg_days_to_close, "#f3e5f5", "#6f42c1", "#4a148c"), unsafe_allow_html=True)
    with met7: st.markdown(create_kpi_card("Overdue 🚨", overdue_count, "#ffebee" if overdue_count > 0 else "#e8f5e9", "#dc3545" if overdue_count > 0 else "#28a745", "#721c24" if overdue_count > 0 else "#155724"), unsafe_allow_html=True)

    # --- ADVANCED EFFICIENCY MATH ---
    for c in ALL_DATE_COLS:
        if c in f_df: f_df[c] = pd.to_datetime(f_df[c], errors='coerce')

    if 'Feedback from ITC on TD (date)' in f_df and 'Submitted date to ITC for TD approval' in f_df:
        f_df['Stage1_Days'] = (f_df['Feedback from ITC on TD (date)'] - f_df['Submitted date to ITC for TD approval']).dt.days
    if 'Actual Bid Opening date' in f_df and 'Actual Publication date' in f_df:
        f_df['Stage2_Days'] = (f_df['Actual Bid Opening date'] - f_df['Actual Publication date']).dt.days
    if 'Date evaluation report is released from ITC' in f_df and 'Date bids are submitted for ITC evaluation' in f_df:
        f_df['Stage3_Days'] = (f_df['Date evaluation report is released from ITC'] - f_df['Date bids are submitted for ITC evaluation']).dt.days
    
    if 'Actual contract date' in f_df and 'SMT date' in f_df:
        f_df['Calc_Contract_Date'] = f_df['Actual contract date'].fillna(pd.to_datetime(today_str))
        f_df['Calc_Start_Date'] = f_df['SMT date'].fillna(f_df.get('Submitted date to ITC for TD approval'))
        f_df['Overall_Days'] = (f_df['Calc_Contract_Date'] - f_df['Calc_Start_Date']).dt.days

    if 'Budget FRW' in f_df.columns:
        f_df['Budget FRW'] = pd.to_numeric(f_df['Budget FRW'], errors='coerce').fillna(0)
    else:
        f_df['Budget FRW'] = 0.0

    s1_avg = f_df.get('Stage1_Days', pd.Series(dtype=float)).mean()
    s2_avg = f_df.get('Stage2_Days', pd.Series(dtype=float)).mean()
    s3_avg = f_df.get('Stage3_Days', pd.Series(dtype=float)).mean()
    oa_avg = f_df.get('Overall_Days', pd.Series(dtype=float)).mean()

    s1_display = f"{s1_avg:.1f}" if pd.notna(s1_avg) else "-"
    s2_display = f"{s2_avg:.1f}" if pd.notna(s2_avg) else "-"
    s3_display = f"{s3_avg:.1f}" if pd.notna(s3_avg) else "-"
    oa_display = f"{oa_avg:.1f}" if pd.notna(oa_avg) else "-"

    # --- ADVANCED EXPANDER ---
    with st.expander("📈 View Advanced Efficiency KPIs & Allocation Charts", expanded=True):
        tab_eff, tab_closure_chart, tab_itc_chart, tab_officer_chart = st.tabs(["🚀 Efficiency Stage KPIs", "📊 Days taken to close a tender", "📊 ITC Status Distribution", "📊 Officer Workload Allocation"])
        
        with tab_eff:
            e1, e2, e3, e4, e5 = st.columns(5)
            e1.markdown(f"<div class='eff-card bg-green'><div class='eff-title'>Total Budget (Filtered)</div><div class='eff-value' style='color:#28a745;'>{format_budget(f_df['Budget FRW'].sum())}</div><div class='eff-sub'>{len(f_df)} Active Tenders</div></div>", unsafe_allow_html=True)
            e2.markdown(f"<div class='eff-card bg-purple'><div class='eff-title'>TD Approval Stage</div><div class='eff-value' style='color:#6f42c1;'>{s1_display} <span style='font-size:12px'>Days</span></div><div class='eff-sub'>Submission -> Feedback</div></div>", unsafe_allow_html=True)
            e3.markdown(f"<div class='eff-card bg-blue'><div class='eff-title'>Market Stage</div><div class='eff-value' style='color:#007bff;'>{s2_display} <span style='font-size:12px'>Days</span></div><div class='eff-sub'>Publication -> Bid Opening</div></div>", unsafe_allow_html=True)
            e4.markdown(f"<div class='eff-card bg-orange'><div class='eff-title'>Evaluation Stage</div><div class='eff-value' style='color:#fd7e14;'>{s3_display} <span style='font-size:12px'>Days</span></div><div class='eff-sub'>Bids to ITC -> Eval Report</div></div>", unsafe_allow_html=True)
            e5.markdown(f"<div class='eff-card bg-dark'><div class='eff-title'>OVERALL LIFECYCLE</div><div class='eff-value' style='color:white;'>{oa_display} <span style='font-size:12px; color:#e0f7fa;'>Days</span></div><div class='eff-sub'>SMT Date -> Contract Signed</div></div>", unsafe_allow_html=True)

        color_map = {'Awarded': '#28a745', 'Cancelled': '#dc3545', 'Completed': '#6f42c1', 'Under Evaluation': '#ffc107', 'Published': '#17a2b8', 'Planned': '#6c757d'}

        with tab_closure_chart:
            df_closure = valid_tenders[valid_tenders.get('ITC Team', pd.Series()).astype(str).str.strip() != '']
            if not df_closure.empty:
                df_closure_grouped = df_closure.groupby('ITC Team').agg(min_days=('Days_to_Close', 'min'), max_days=('Days_to_Close', 'max'), avg_days=('Days_to_Close', 'mean')).reset_index()
                df_closure_grouped['Efficiency_Score'] = df_closure_grouped['avg_days'].apply(lambda x: min(100, round(100 * (sla_days / x))) if x > 0 else 100)
                df_closure_grouped['custom_text'] = df_closure_grouped.apply(lambda row: f"(min={int(row['min_days'])}, avg={row['avg_days']:.1f}, max={int(row['max_days'])}) | Efficiency: {row['Efficiency_Score']}%", axis=1)
                st.plotly_chart(fig_closure_chart(df_closure_grouped, sla_days), use_container_width=True)

        with tab_itc_chart:
            df_itc = f_df[f_df.get('ITC Team', pd.Series()).astype(str).str.strip() != '']
            if not df_itc.empty:
                df_itc_counts = df_itc.groupby(['ITC Team', 'Current status']).size().reset_index(name='Count')
                st.plotly_chart(fig_status_counts_chart(df_itc_counts, 'ITC Team', "ITC Status"), use_container_width=True)

        with tab_officer_chart:
            df_off = f_df[f_df.get('Responsible officer', pd.Series()).astype(str).str.strip() != '']
            if not df_off.empty:
                df_off_counts = df_off.groupby(['Responsible officer', 'Current status']).size().reset_index(name='Count')
                st.plotly_chart(fig_status_counts_chart(df_off_counts, 'Responsible officer', "Responsible Officer"), use_container_width=True)

    # --- AG-GRID TRACKER ---
    action_container_top = st.empty() 
    
    display_df = f_df.copy()
    
    display_df.rename(columns={
        'Stage1_Days': 'TD Approval (Days)',
        'Stage2_Days': 'Market (Days)',
        'Stage3_Days': 'Evaluation (Days)',
        'Overall_Days': 'Overall Lifecycle (Days)',
        'Days_to_Close': 'Days Open'
    }, inplace=True)

    for c in ALL_DATE_COLS:
        if c in display_df: display_df[c] = display_df[c].dt.strftime('%Y-%m-%d').fillna('')

    calc_cols = ['TD Approval (Days)', 'Market (Days)', 'Evaluation (Days)', 'Overall Lifecycle (Days)', 'Days Open']
    for c in calc_cols:
        if c in display_df.columns:
            display_df[c] = display_df[c].apply(lambda x: str(int(x)) if pd.notna(x) else "")

    logical_col_order = [
        'S/N', 'Tender reference number', 'Title of the tender', 'Current status', 'Category', 'Method of tender', 'Responsible officer', 'ITC Team', 'Budget FRW', 'Source of funds', 
        'SMT date', 
        'Submitted date to ITC for TD approval', 'Feedback from ITC on TD (date)', 'TD Approval (Days)',
        'Planned Publication date', 'Actual Publication date', 'Planned Bid opening date', 'Actual Bid Opening date', 'Market (Days)',
        'Date bids are submitted for ITC evaluation', 'Date evaluation report is released from ITC', 'Evaluation (Days)',
        'Planned Provisional Notification date', 'Actual provisional Notification date ', 'Planned Contract signing date', 'Actual contract date', 'Overall Lifecycle (Days)',
        'Date awarded', 'Days Open',
        'Comments '
    ]

    ordered_cols = [c for c in logical_col_order if c in display_df.columns]
    for c in display_df.columns:
        if c not in ordered_cols: ordered_cols.append(c)
    display_df = display_df[ordered_cols]

    drop_cols = ['fiscal_year', 'Sub_Date', 'Award_Date', 'Calc_Award_Date', 'Calc_Contract_Date', 'Calc_Start_Date', 'Is_Overdue']
    display_df = display_df.drop(columns=[c for c in drop_cols if c in display_df.columns])

    gb = GridOptionsBuilder.from_dataframe(display_df)
    
    if 'Is_Overdue' in display_df.columns: gb.configure_column('Is_Overdue', hide=True)
    if 'id' in display_df.columns: gb.configure_column('id', hide=True, editable=False, suppressColumnsToolPanel=True)
    
    gb.configure_default_column(
        wrapText=True, 
        autoHeight=True, 
        editable=True, 
        minWidth=150,
        tooltipValueGetter=JsCode("function(params) { return params.value ? String(params.value) : ''; }")
    )
    
    stage1_vg = JsCode("""function(params) { 
        let s = params.data['Submitted date to ITC for TD approval']; 
        let e = params.data['Feedback from ITC on TD (date)']; 
        if(!s || s === '' || !e || e === '') return ''; 
        return Math.round((new Date(e) - new Date(s))/(1000*60*60*24)); 
    }""")
    
    stage2_vg = JsCode("""function(params) { 
        let s = params.data['Actual Publication date']; 
        let e = params.data['Actual Bid Opening date']; 
        if(!s || s === '' || !e || e === '') return ''; 
        return Math.round((new Date(e) - new Date(s))/(1000*60*60*24)); 
    }""")
    
    stage3_vg = JsCode("""function(params) { 
        let s = params.data['Date bids are submitted for ITC evaluation']; 
        let e = params.data['Date evaluation report is released from ITC']; 
        if(!s || s === '' || !e || e === '') return ''; 
        return Math.round((new Date(e) - new Date(s))/(1000*60*60*24)); 
    }""")
    
    overall_vg = JsCode("""function(params) { 
        let s = params.data['SMT date']; 
        if (!s || s.trim() === '') s = params.data['Submitted date to ITC for TD approval'];
        if (!s || s.trim() === '') return ''; 
        
        let e = params.data['Actual contract date']; 
        let d2 = (e && e.trim() !== '') ? new Date(e) : new Date(); 
        return Math.round((d2 - new Date(s))/(1000*60*60*24)); 
    }""")
    
    days_open_vg = JsCode("""function(params) { 
        let s = params.data['Submitted date to ITC for TD approval']; 
        if(!s || s.trim() === '') return ''; 
        let e = params.data['Date awarded']; 
        let d2 = (e && e.trim() !== '') ? new Date(e) : new Date(); 
        return Math.round((d2 - new Date(s))/(1000*60*60*24)); 
    }""")

    gb.configure_column('TD Approval (Days)', valueGetter=stage1_vg, editable=False, width=130)
    gb.configure_column('Market (Days)', valueGetter=stage2_vg, editable=False, width=130)
    gb.configure_column('Evaluation (Days)', valueGetter=stage3_vg, editable=False, width=130)
    gb.configure_column('Overall Lifecycle (Days)', valueGetter=overall_vg, editable=False, width=130)
    gb.configure_column('Days Open', valueGetter=days_open_vg, editable=False, width=110)
    
    for col in display_df.columns:
        gb.configure_column(col, headerTooltip=col)
    
    dynamic_cellstyle = JsCode(f"""
    function(params) {{
        if (!params.colDef || !params.colDef.field) return null;
        
        const statusMap = {json.dumps(status_color_map)};
        const itcMap = {json.dumps(itc_color_map)};
        const catMap = {json.dumps(cat_color_map)};
        const field = params.colDef.field;
        let bgColor = null;
        let tColor = 'black';
        
        if (params.data.Is_Overdue === true) {{
            return {{'backgroundColor': '#ffebee', 'color': 'black'}};
        }}
        
        if (field === 'Current status' && statusMap[params.value]) bgColor = statusMap[params.value];
        else if (field === 'ITC Team' && itcMap[params.value]) bgColor = itcMap[params.value];
        else if (field === 'Category' && catMap[params.value]) bgColor = catMap[params.value];
        
        if (bgColor) {{
            let hexcolor = bgColor.replace("#", "");
            if (hexcolor.length === 3) hexcolor = hexcolor.split('').map(function(hex){{return hex+hex}}).join('');
            var r = parseInt(hexcolor.substr(0,2),16);
            var g = parseInt(hexcolor.substr(2,2),16);
            var b = parseInt(hexcolor.substr(4,2),16);
            var yiq = ((r*299)+(g*587)+(b*114))/1000;
            tColor = (yiq >= 128) ? 'black' : 'white';
            return {{'backgroundColor': bgColor, 'color': tColor, 'fontWeight': 'bold'}};
        }}
        
        const computedCols = ['TD Approval (Days)', 'Market (Days)', 'Evaluation (Days)', 'Overall Lifecycle (Days)', 'Days Open'];
        if (computedCols.includes(field)) {{
            return {{'backgroundColor': '#e9ecef', 'color': '#0275d8', 'fontWeight': '900', 'borderLeft': '3px solid #0275d8'}};
        }}
        
        const stage1Cols = ['Submitted date to ITC for TD approval', 'Feedback from ITC on TD (date)'];
        const stage2Cols = ['Planned Publication date', 'Actual Publication date', 'Planned Bid opening date', 'Actual Bid Opening date'];
        const stage3Cols = ['Date bids are submitted for ITC evaluation', 'Date evaluation report is released from ITC'];
        const stage4Cols = ['Planned Provisional Notification date', 'Actual provisional Notification date ', 'Planned Contract signing date', 'Actual contract date', 'Date awarded'];
        
        if (stage1Cols.includes(field)) return {{'backgroundColor': '#e2d4f5', 'fontWeight': '600'}};
        if (stage2Cols.includes(field)) return {{'backgroundColor': '#cce5ff', 'fontWeight': '600'}};
        if (stage3Cols.includes(field)) return {{'backgroundColor': '#ffdfb3', 'fontWeight': '600'}};
        if (stage4Cols.includes(field)) return {{'backgroundColor': '#c3e6cb', 'fontWeight': '600'}};
        
        return null;
    }}
    """)

    gb.configure_grid_options(
        singleClickEdit=True, 
        domLayout='normal', 
        getRowStyle=dynamic_cellstyle,
        enableBrowserTooltips=True,
        update_on=['cellValueChanged', 'selectionChanged']
    )
    gb.configure_selection(selection_mode="single", use_checkbox=True)
    
    date_formatter = JsCode("function(params) { if (!params.value) return ''; let dateParts = params.value.split('-'); if (dateParts.length !== 3) return params.value; const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']; return parseInt(dateParts[2]) + '-' + months[parseInt(dateParts[1])-1] + '-' + dateParts[0]; }")
    custom_date_editor = JsCode("class DatePickerEditor { init(params) { this.eInput = document.createElement('input'); this.eInput.type = 'date'; this.eInput.value = params.value || ''; this.eInput.style.width = '100%'; this.eInput.style.padding = '5px'; this.eInput.style.border = 'none'; } getGui() { return this.eInput; } afterGuiAttached() { this.eInput.focus(); } getValue() { return this.eInput.value; } }")

    for col in ALL_DATE_COLS:
        if col in display_df.columns:
            gb.configure_column(col, editable=True, width=160, cellEditor=custom_date_editor, valueFormatter=date_formatter, cellStyle=dynamic_cellstyle)

    if 'Budget FRW' in display_df.columns: gb.configure_column('Budget FRW', type=["numericColumn"], editable=True)
    if 'Current status' in display_df.columns: gb.configure_column("Current status", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': STATUS_OPTIONS}, width=150, pinned='right', cellStyle=dynamic_cellstyle)
    if 'Category' in display_df.columns: gb.configure_column("Category", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': CAT_OPTIONS}, width=150, cellStyle=dynamic_cellstyle)
    if 'ITC Team' in display_df.columns: gb.configure_column("ITC Team", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': ITC_OPTIONS}, width=120, cellStyle=dynamic_cellstyle)
    if 'Method of tender' in display_df.columns: gb.configure_column("Method of tender", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': METHOD_OPTIONS}, width=160)
    if 'S/N' in display_df.columns: gb.configure_column('S/N', width=80, pinned='left', checkboxSelection=True)
    if 'Tender reference number' in display_df.columns: gb.configure_column('Tender reference number', width=250, pinned='left', editable=False)
    if 'Title of the tender' in display_df.columns: gb.configure_column('Title of the tender', width=400, minWidth=400)

    # 🚨 STICKY HEADER CSS ENFORCED HERE
    custom_css = {
        ".ag-header": {
            "position": "sticky !important", 
            "top": "0px !important", 
            "z-index": "1000 !important",
            "background-color": "#0275d8 !important", 
            "border-bottom": "2px solid #0056b3 !important"
        },
        ".ag-header-row": {"background-color": "transparent !important", "color": "white !important"},
        ".ag-header-cell-label": {"color": "white !important", "font-weight": "bold !important"}
    }
    
    # Fixed-height grid: the rows scroll INSIDE it, so the blue header row always stays visible.
    grid_height = int(min(700, max(260, 110 + 62 * len(display_df))))

    grid_response = AgGrid(
        display_df, 
        gridOptions=gb.build(), 
        data_return_mode=DataReturnMode.AS_INPUT, 
        fit_columns_on_grid_load=False, 
        theme='streamlit', 
        allow_unsafe_jscode=True, 
        custom_css=custom_css,
        height=grid_height,
        key=f"tender_main_grid_v8_{st.session_state.get('grid_ver', 0)}"
    )

    # --- ADVANCED EDITOR PLACEMENT ---
    selected_rows = grid_response.get("selected_rows")
    has_selection = False
    if isinstance(selected_rows, pd.DataFrame) and not selected_rows.empty:
        has_selection, selected_data = True, selected_rows.iloc[0].to_dict()
    elif isinstance(selected_rows, list) and len(selected_rows) > 0:
        has_selection, selected_data = True, selected_rows[0]

    if has_selection:
        with action_container_top.container():
            st.markdown("### 🛠️ Selected Tender Actions")
            c1, c2, c3, _ = st.columns([2, 2, 2, 6])
            with c1:
                if st.button("✏️ Edit Advanced Details", type="primary", use_container_width=True): edit_row_dialog(selected_data, selected_fy)
            with c2:
                if st.button("📄 Duplicate Row", type="secondary", use_container_width=True): duplicate_row_dialog(selected_data, selected_fy)
            with c3:
                if st.button("🗑️ Delete Selected Row", type="secondary", use_container_width=True): delete_row_dialog(selected_data)
            st.markdown("<hr style='margin: 10px 0px;'/>", unsafe_allow_html=True)

    # --- SQLITE INLINE EDIT SYNC (vectorised: compares whole columns at once and saves in a single transaction) ---
    edited_df = grid_response['data']
    rename_map_now = db.get_rename_map()
    editable_cols = set(rename_map_now.values()) - {'Tender reference number'}
    ui_to_db = {v: k for k, v in rename_map_now.items()}
    updates, date_changed = tu.compute_inline_changes(df, edited_df, editable_cols, set(ALL_DATE_COLS), ui_to_db)
    if updates:
        db.update_cells_bulk(updates)
    if date_changed: st.rerun()

# 🚨 TAB 2: SECURE IMPORT PORTAL (upload / paste from Excel / type in a table) 🚨
class _NamedBytes(io.BytesIO):
    def __init__(self, data, name):
        super().__init__(data)
        self.name = name

@st.cache_data(show_spinner=False, max_entries=8)
def _read_import_file(name, data, targets):
    return tu.read_uploaded_file(_NamedBytes(data, name), list(targets))

@st.cache_data(show_spinner=False, max_entries=4)
def _template_bytes(columns):
    return tu.build_template_bytes(list(columns))

def _typed_table_template(cols, rows=5):
    data = {}
    for c in cols:
        if c in ALL_DATE_COLS: data[c] = pd.Series([pd.NaT] * rows, dtype="datetime64[ns]")
        elif c == "Budget FRW": data[c] = pd.Series([None] * rows, dtype="float64")
        else: data[c] = pd.Series([None] * rows, dtype="object")
    return pd.DataFrame(data)

IMPORT_MODES = ["📁 Upload Excel", "📋 Paste from Excel", "⌨️ Type in a table"]

@st.fragment
def render_upload_tab(active_fy):
    # This block is a fragment: clicking/typing inside it does NOT re-run the dashboard above, so it stays fast.
    st.subheader(f"📂 Upload Data to [{active_fy}]")
    st.markdown("**You can upload standard Excel (.xlsx) or CSV files.**")

    flash = st.session_state.pop("import_flash", None)
    if flash: st.success(flash)
    ver = st.session_state.get("import_ver", 0)

    targets = list(db.get_rename_map().values())
    template_cols = [c for c in tu.TEMPLATE_ORDER if c in targets] + [c for c in targets if c not in tu.TEMPLATE_ORDER]
    status_choices = [o for o in STATUS_OPTIONS if o]

    chain = []
    for c in template_cols:
        label = c.strip().upper()
        if c == "Tender reference number": chain.append(f"<span class='req'>{label} (REQUIRED)</span>")
        elif c in ("Title of the tender", "SMT date", "Submitted date to ITC for TD approval"): chain.append(f"<span class='rec'>{label}</span>")
        else: chain.append(label)
    st.markdown(
        "<div class='import-info'><b>Column order:</b> " + " &rarr; ".join(chain) + "<br><br>"
        "<span class='req'>Red = required</span> (a row with no reference but with a title gets an automatic reference like N/A-1; completely empty rows are skipped) &middot; "
        "<span class='rec'>orange = strongly recommended</span> (they drive the days and efficiency calculations) &middot; the rest are optional. "
        "Sheets with other headers (e.g. 'REF', 'STATUS', 'DESCRIPTION', 'TENDER TITLE') are matched automatically. "
        "The Days columns are calculated for you.</div>", unsafe_allow_html=True)

    t1, t2 = st.columns([1, 3])
    with t1:
        st.download_button("⬇️ Download Excel Template", data=_template_bytes(tuple(template_cols)), file_name="Tender_Import_Template.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with t2:
        with st.expander("📋 See what each column means"):
            guide = pd.DataFrame({"Column": [c.strip() for c in template_cols],
                                  "Meaning": [tu.COLUMN_HELP.get(c, "Date (YYYY-MM-DD or DD/MM/YYYY)" if c in ALL_DATE_COLS else "Optional.") for c in template_cols]})
            st.dataframe(guide, hide_index=True, use_container_width=True)

    mode = st.radio("How would you like to add items?", IMPORT_MODES, horizontal=True, key=f"imp_mode_{ver}")

    o1, o2 = st.columns(2)
    with o1:
        default_status = st.selectbox("Status for rows that have none", status_choices,
                                      index=status_choices.index("Planned") if "Planned" in status_choices else 0, key=f"imp_status_{ver}")
    with o2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        skip_existing = st.checkbox("Skip rows that already exist (same tender reference number)", value=True, key=f"imp_skip_{ver}",
                                    help="Ticked: existing tenders are left untouched. Unticked: existing tenders are updated with the cells the file filled in (blank cells never erase data).")

    raw_df, note = pd.DataFrame(), ""
    try:
        if mode == IMPORT_MODES[0]:
            up = st.file_uploader("Upload File", type=["csv", "xlsx", "xls"], key=f"imp_file_{ver}")
            if up is not None: raw_df = _read_import_file(up.name, up.getvalue(), tuple(targets))
        elif mode == IMPORT_MODES[1]:
            txt = st.text_area("Paste rows copied from Excel here (include the header row)", height=200, key=f"imp_paste_{ver}",
                               placeholder="Select the cells in Excel, press Ctrl+C, click here and press Ctrl+V")
            raw_df, used_template_order = tu.parse_pasted_text(txt, targets)
            if used_template_order: note = "ℹ️ No header row was found, so the columns were read in the template column order."
        else:
            cfg = {}
            for c in template_cols:
                if c in ALL_DATE_COLS: cfg[c] = st.column_config.DateColumn(c.strip(), format="YYYY-MM-DD")
                elif c == "Budget FRW": cfg[c] = st.column_config.NumberColumn(c.strip(), min_value=0, format="%.0f")
                elif c == "Current status": cfg[c] = st.column_config.SelectboxColumn(c.strip(), options=status_choices)
                elif c == "Category": cfg[c] = st.column_config.SelectboxColumn(c.strip(), options=[o for o in CAT_OPTIONS if o]) if len(CAT_OPTIONS) > 1 else st.column_config.TextColumn(c.strip())
                elif c == "Method of tender": cfg[c] = st.column_config.SelectboxColumn(c.strip(), options=[o for o in METHOD_OPTIONS if o]) if len(METHOD_OPTIONS) > 1 else st.column_config.TextColumn(c.strip())
                elif c == "ITC Team": cfg[c] = st.column_config.SelectboxColumn(c.strip(), options=[o for o in ITC_OPTIONS if o]) if len(ITC_OPTIONS) > 1 else st.column_config.TextColumn(c.strip())
                else: cfg[c] = st.column_config.TextColumn(c.strip())
            st.caption("Click a cell and type. Use the + at the bottom of the table (or just keep going) to add rows; tick a row's left box and press Delete to remove it.")
            raw_df = st.data_editor(_typed_table_template(template_cols), num_rows="dynamic", use_container_width=True,
                                    column_config=cfg, hide_index=True, key=f"imp_typed_{ver}")
    except Exception as e:
        st.error(f"Could not read this data: {e}")
        return

    if raw_df is None or raw_df.empty:
        return
    if note: st.info(note)

    other_options = {"Category": [o for o in CAT_OPTIONS if o], "Method of tender": [o for o in METHOD_OPTIONS if o], "ITC Team": [o for o in ITC_OPTIONS if o]}
    rep = tu.prepare_import(raw_df, targets, set(ALL_DATE_COLS), STATUS_OPTIONS, default_status, other_options,
                            db.get_existing_refs(active_fy, include_deleted=False), skip_existing, db.get_auto_ref_titles(active_fy))
    cnt, rows = rep["counts"], rep["rows"]
    if not rep["preview"].empty or cnt["blank"]:
        parts = [f"✅ **{cnt['new']} new**"]
        if cnt["exists"]: parts.append(f"{'⏭️' if skip_existing else '✏️'} {cnt['exists']} already exist ({'skipped' if skip_existing else 'will be updated'})")
        if cnt["repeated"]: parts.append(f"🔁 {cnt['repeated']} repeated inside the file (skipped)")
        if cnt["auto_ref"]: parts.append(f"🏷️ {cnt['auto_ref']} given an automatic reference")
        if cnt["blank"]: parts.append(f"▫️ {cnt['blank']} empty row(s) ignored")
        st.markdown(" · ".join(parts))
        if cnt["bad_dates"]: st.warning(f"{cnt['bad_dates']} date value(s) could not be read and were left blank. Use YYYY-MM-DD or DD/MM/YYYY.")
        if cnt["bad_budget"]: st.warning(f"{cnt['bad_budget']} budget value(s) were not numbers and were set to 0.")
        if cnt["status_fixed"]: st.warning(f"{cnt['status_fixed']} row(s) had a status that is not in your status list; they were set to '{default_status}'.")
        if rep["ignored"]: st.caption("Columns not recognised (ignored): " + ", ".join(rep["ignored"]))
        if not rep["preview"].empty:
            st.dataframe(rep["preview"], hide_index=True, use_container_width=True, height=int(min(380, 60 + 36 * len(rep["preview"]))))

    if st.button(f"✅ Add {len(rows)} row(s) to [{active_fy}]", type="primary", disabled=(len(rows) == 0), key=f"imp_go_{ver}"):
        with st.spinner("Saving..."):
            try: db.backup_db("pre-import", keep=10)      # safety copy of the database before every import
            except Exception: pass
            res = db.import_tenders(active_fy, rows, skip_existing)
        st.session_state["import_flash"] = (f"Success! Added {res['inserted']} NEW tenders" + (f", updated {res['updated']}" if res['updated'] else "") +
                                            (f". {res['skipped']} existing tenders were skipped to protect your data." if res['skipped'] else "."))
        st.session_state["import_ver"] = ver + 1
        bump_grid()
        st.rerun()

    st.divider()
    with st.expander("💾 Database backup"):
        st.caption("Download a complete copy of all your data (every fiscal year, dropdowns, edit trail). Do this before deploying new code.")
        if st.button("Create backup file", key="bk_make"):
            st.session_state["bk_bytes"] = db.get_backup_bytes()
            st.session_state["bk_name"] = f"tender_tracker_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        if st.session_state.get("bk_bytes"):
            st.download_button("⬇️ Download backup", data=st.session_state["bk_bytes"], file_name=st.session_state.get("bk_name", "tender_tracker_backup.db"),
                               mime="application/octet-stream", key="bk_dl")

with tab_upload:
    render_upload_tab(selected_fy)

with tab_logs:
    st.subheader("📝 Edit Trail & Activity Logs")
    logs_df = db.get_logs()
    if not logs_df.empty: st.dataframe(logs_df, hide_index=True, use_container_width=True)

with tab_deleted:
    st.subheader(f"🗑️ Deleted Tenders for [{selected_fy}]")
    deleted_df = db.get_deleted_tenders(selected_fy)
    if not deleted_df.empty: st.dataframe(deleted_df[[c for c in ['id', 'S/N', 'Tender reference number', 'Title of the tender', 'Deleted By', 'Deleted By (Email)', 'Deleted At'] if c in deleted_df.columns]], hide_index=True, use_container_width=True)