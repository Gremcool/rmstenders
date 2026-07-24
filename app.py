import streamlit as st
import pandas as pd
import os
import io
import time
from datetime import datetime
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode, JsCode
from streamlit_quill import st_quill
import plotly.express as px
import db

# --- PAGE CONFIG ---
st.set_page_config(page_title="RMS Tender Allocation Tracker", layout="wide", initial_sidebar_state="collapsed")
db.init_db()

# --- CUSTOM CSS ---
st.markdown("""
    <style>
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="collapsedControl"] { display: none !important; }
        .block-container { padding-top: 2rem !important; padding-bottom: 1rem !important; }
        .custom-title {
            margin-top: 0px; font-size: 30px; font-weight: 800;
            background: -webkit-linear-gradient(45deg, #1e3c72, #2a5298);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin-bottom: 2px; line-height: 1.2;
        }
        .custom-subtitle { color: #6c757d; font-size: 14px; margin-bottom: 0px; }
    </style>
""", unsafe_allow_html=True)

def create_kpi_card(title, value, bg_color, text_color, border_color):
    return f"""
    <div style="background-color: {bg_color}; padding: 12px 5px; border-radius: 8px; text-align: center; border: 1px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 15px;">
        <p style="margin:0; color: {text_color}; font-size: 13px; font-weight: 700; text-transform: uppercase;">{title}</p>
        <h2 style="margin:0; color: {text_color}; font-size: 28px; font-weight: 800; padding-top: 4px;">{value}</h2>
    </div>
    """

METHOD_OPTIONS = ["", "NCB", "ICB", "RFQ", "Direct Procurement", "Framework", "Other"]
ITC_OPTIONS = ["", "ITC1", "ITC2", "ITC3", "ITC4"]
STATUS_OPTIONS = ["", "Planned", "Draft", "Published", "Under Evaluation", "Awarded", "Cancelled"]

# --- POP-UP DIALOGS ---
@st.dialog("✏️ Edit Standard Details", width="large")
def edit_row_dialog(row_data, active_fy):
    st.markdown(f"**Editing Tender Ref:** `{row_data.get('Tender reference number', 'N/A')}`")
    
    # Grab the unique ID to prevent Streamlit widget state leakage
    t_id = row_data.get('id', 'new')
    
    status_idx = STATUS_OPTIONS.index(row_data.get("Current status", "")) if row_data.get("Current status") in STATUS_OPTIONS else 0
    method_idx = METHOD_OPTIONS.index(row_data.get("Method of tender", "")) if row_data.get("Method of tender") in METHOD_OPTIONS else 0
    raw_itc = str(row_data.get("ITC", "")).strip().upper().replace(" ", "")
    itc_idx = ITC_OPTIONS.index(raw_itc) if raw_itc in ITC_OPTIONS else 0

    # Safely parse dates to avoid NaTType errors
    raw_smt = pd.to_datetime(row_data.get("SMT date/PP Planned date of publication", ""), errors='coerce')
    default_smt = raw_smt.date() if pd.notna(raw_smt) else None

    raw_itc_date = pd.to_datetime(row_data.get("Submitted date to ITC for TD approval", ""), errors='coerce')
    default_itc_date = raw_itc_date.date() if pd.notna(raw_itc_date) else None

    raw_awarded_date = pd.to_datetime(row_data.get("Date awarded", ""), errors='coerce')
    default_awarded_date = raw_awarded_date.date() if pd.notna(raw_awarded_date) else None

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        new_t_no = st.text_input("Tender No", value=row_data.get("Tender No", ""))
        new_user = st.text_input("End user", value=row_data.get("End user", ""))
        new_status = st.selectbox("Current status", STATUS_OPTIONS, index=status_idx)
    with c2:
        new_smt = st.date_input("SMT / Planned date", value=default_smt)
        new_method = st.selectbox("Method of tender", METHOD_OPTIONS, index=method_idx)
        new_officer = st.text_input("Responsible officer", value=row_data.get("Responsible officer", ""))
    with c3:
        new_itc = st.selectbox("ITC", ITC_OPTIONS, index=itc_idx)
        new_itc_date = st.date_input("Date submitted to ITC", value=default_itc_date)
    with c4:
        new_awarded_date = st.date_input("Date awarded", value=default_awarded_date)

    st.divider()
    
    # Safely format strings for Quill to avoid 'nan' injection
    val_title = row_data.get("Title of the tender", "")
    val_title = "" if pd.isna(val_title) else str(val_title)
    
    val_reason = row_data.get("Reason of approval/for initiating tender", "")
    val_reason = "" if pd.isna(val_reason) else str(val_reason)
    
    val_itc_com = row_data.get("Comments from ITC", "")
    val_itc_com = "" if pd.isna(val_itc_com) else str(val_itc_com)

    # RESTORED TITLES
    st.markdown("### 📝 Title of the tender")
    new_title = st_quill(value=val_title, placeholder="Write title here...", html=True, key=f"quill_title_{t_id}")
    
    st.markdown("### 📋 Reason of approval / for initiating tender")
    new_reason = st_quill(value=val_reason, placeholder="Write reason here...", html=True, key=f"quill_reason_{t_id}")
    
    st.markdown("### 💬 Comments from ITC")
    new_itc_com = st_quill(value=val_itc_com, placeholder="Write comments here...", html=True, key=f"quill_itc_com_{t_id}")
    
    if st.button("Save Changes", type="primary", width="stretch"):
        updated_row = {
            'fiscal_year': active_fy, 'Tender No': new_t_no, 'Tender reference number': row_data.get("Tender reference number", ""),
            'Title of the tender': new_title, 'End user': new_user, 'SMT date/PP Planned date of publication': new_smt.strftime('%Y-%m-%d') if new_smt else "",
            'Reason of approval/for initiating tender': new_reason, 'Method of tender': new_method, 'Responsible officer': new_officer,
            'ITC': new_itc, 'Submitted date to ITC for TD approval': new_itc_date.strftime('%Y-%m-%d') if new_itc_date else "",
            'Comments from ITC': new_itc_com, 'Current status': new_status, 'Date awarded': new_awarded_date.strftime('%Y-%m-%d') if new_awarded_date else ""
        }
        db.upsert_tender(updated_row)
        st.success("Changes Saved!")
        time.sleep(0.5)
        st.rerun()

@st.dialog("🗑️ Confirm Deletion")
def delete_row_dialog(row_data):
    st.warning(f"Are you sure you want to delete Tender Ref: `{row_data.get('Tender reference number', 'N/A')}`?")
    user_name = st.text_input("Enter your name to confirm deletion:")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancel", width="stretch"): st.rerun()
    with c2:
        if st.button("Delete Permanently", type="primary", width="stretch"):
            if not user_name.strip():
                st.error("⚠️ Your name is required.")
            else:
                db.delete_tender(row_data['id'], user_name.strip())
                st.success("Tender deleted.")
                time.sleep(0.5)
                st.rerun()

# --- HEADER & FISCAL YEAR MANAGEMENT ---
col_logo, col_title = st.columns([1, 15])
with col_logo:
    if os.path.exists("logo.jpg"): st.image("logo.jpg", width="stretch")
    else: st.markdown("<h1 style='text-align: center; margin: 0;'>🏢</h1>", unsafe_allow_html=True)

with col_title:
    st.markdown("<div class='custom-title'>RMS PROCUREMENT TENDER TRACKER</div>", unsafe_allow_html=True)
    st.markdown("<div class='custom-subtitle'>Monitor fair allocation and track tender statuses across fiscal years.</div>", unsafe_allow_html=True)
st.markdown("<hr style='margin-top: 15px; margin-bottom: 15px; border: 0; border-top: 1px solid #eee;' />", unsafe_allow_html=True)

fiscal_years = db.get_fiscal_years()

col_fy1, col_fy2 = st.columns([1, 1])
with col_fy1:
    selected_fy = st.selectbox("📂 Active Fiscal Year Dashboard", fiscal_years)
with col_fy2:
    with st.expander("➕ Initialize New Fiscal Year Workspace"):
        new_fy = st.text_input("Enter Year (e.g., 2026-2027)")
        do_migrate = st.checkbox("Migrate pending/open tenders from active year?", value=True)
        if st.button("Initialize Year"):
            if new_fy and new_fy not in fiscal_years:
                db.add_fiscal_year(new_fy.strip())
                if do_migrate and selected_fy:
                    db.migrate_pending_tenders(selected_fy, new_fy.strip())
                st.success(f"Workspace {new_fy} created!")
                st.rerun()
            else:
                st.error("Invalid or duplicate year.")

st.markdown("<hr style='margin-top: 15px; margin-bottom: 15px; border: 0; border-top: 1px solid #eee;' />", unsafe_allow_html=True)

# --- TABS ---
tab_tracker, tab_upload, tab_logs, tab_deleted = st.tabs(["📊 Tender Tracker & Analytics", "📂 Upload Data", "📝 Edit Trail", "🗑️ Deleted Records"])

with tab_tracker:
    df = db.load_data(selected_fy)
    
    col_setting, col_custom_col = st.columns([2, 10])
    with col_setting:
        sla_days = st.number_input("🚨 SLA Red-Line (Days)", min_value=1, value=21, help="Tenders open beyond this threshold highlight red.")
    with col_custom_col:
        with st.popover("➕ Add Custom Column"):
            new_col_name = st.text_input("Column Name")
            if st.button("Add to Grid"):
                if new_col_name:
                    db.add_custom_column(new_col_name.strip())
                    st.rerun()

    if df.empty:
        st.info(f"💡 Workspace {selected_fy} is ready. Use 'Add New Tender manually' below to generate your first row.")

    if 'Tender No' in df.columns:
        df['Tender No'] = df['Tender No'].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', '')

    for col in ['SMT date/PP Planned date of publication', 'Submitted date to ITC for TD approval', 'Date awarded']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
        elif col == 'Date awarded':
            df['Date awarded'] = ""

    # --- KPI CALCULATION FOR AVG DAYS TO CLOSE & OVERDUE ---
    today_str = datetime.today().strftime('%Y-%m-%d')
    df['Sub_Date'] = pd.to_datetime(df.get('Submitted date to ITC for TD approval', ''), errors='coerce')
    df['Award_Date'] = pd.to_datetime(df.get('Date awarded', ''), errors='coerce')
    
    # Fill un-awarded dates with today to check how long they've been open
    df['Calc_Award_Date'] = df['Award_Date'].fillna(pd.to_datetime(today_str))
    df['Days_to_Close'] = (df['Calc_Award_Date'] - df['Sub_Date']).dt.days

    # Identify overdue tenders
    active_mask = ~df.get('Current status', pd.Series()).isin(['Awarded', 'Cancelled', 'Planned', 'Draft'])
    df['Is_Overdue'] = (df['Days_to_Close'] > sla_days) & active_mask
    overdue_count = int(df['Is_Overdue'].sum()) if not df.empty else 0

    valid_tenders = df.dropna(subset=['Sub_Date']).copy()
    avg_days_to_close = int(valid_tenders['Days_to_Close'].mean()) if not valid_tenders.empty and not valid_tenders['Days_to_Close'].isna().all() else 0

    # Add the formatted display column for the grid
    df['Days taken to close'] = df['Days_to_Close'].apply(lambda x: str(int(x)) if pd.notna(x) else "")

    # --- KPIs ---
    total_tenders = len(df)
    awarded = len(df[df.get("Current status") == "Awarded"]) if not df.empty else 0
    evaluation = len(df[df.get("Current status") == "Under Evaluation"]) if not df.empty else 0
    published = len(df[df.get("Current status") == "Published"]) if not df.empty else 0
    planned = len(df[df.get("Current status") == "Planned"]) if not df.empty else 0

    met1, met2, met3, met4, met5, met6, met7 = st.columns(7)
    with met1: st.markdown(create_kpi_card("Total Tenders", total_tenders, "#f8f9fa", "#2c3e50", "#e9ecef"), unsafe_allow_html=True)
    with met2: st.markdown(create_kpi_card("Awarded ✅", awarded, "#d4edda", "#155724", "#c3e6cb"), unsafe_allow_html=True)
    with met3: st.markdown(create_kpi_card("Evaluation 🔄", evaluation, "#fff3cd", "#856404", "#ffeeba"), unsafe_allow_html=True)
    with met4: st.markdown(create_kpi_card("Published 📢", published, "#cce5ff", "#004085", "#b8daff"), unsafe_allow_html=True)
    with met5: st.markdown(create_kpi_card("Planned ⏳", planned, "#e2e3e5", "#383d41", "#d6d8db"), unsafe_allow_html=True)
    with met6: st.markdown(create_kpi_card("Avg Days Close ⏱️", avg_days_to_close, "#f3e5f5", "#4a148c", "#e1bee7"), unsafe_allow_html=True)
    with met7: st.markdown(create_kpi_card("Overdue 🚨", overdue_count, "#f8d7da" if overdue_count > 0 else "#d4edda", "#721c24" if overdue_count > 0 else "#155724", "#f5c6cb"), unsafe_allow_html=True)

    with st.expander("📈 View Analytics & Allocation Charts", expanded=False):
        tab_closure_chart, tab_itc_chart, tab_officer_chart = st.tabs(["📊 Days taken to close a tender", "📊 ITC Status Distribution", "📊 Officer Workload Allocation"])
        color_map = {'Awarded': '#28a745', 'Cancelled': '#dc3545', 'Under Evaluation': '#ffc107', 'Published': '#17a2b8', 'Planned': '#6c757d', 'Draft': '#adb5bd'}

        with tab_closure_chart:
            df_closure = valid_tenders[valid_tenders.get('ITC', pd.Series()).astype(str).str.strip() != '']
            if not df_closure.empty:
                df_closure_grouped = df_closure.groupby('ITC').agg(min_days=('Days_to_Close', 'min'), max_days=('Days_to_Close', 'max'), avg_days=('Days_to_Close', 'mean')).reset_index()
                df_closure_grouped['avg_days'] = df_closure_grouped['avg_days'].round(1)
                df_closure_grouped['Efficiency_Score'] = df_closure_grouped['avg_days'].apply(lambda x: min(100, round(100 * (sla_days / x))) if x > 0 else 100)
                df_closure_grouped['custom_text'] = df_closure_grouped.apply(lambda row: f"(min={int(row['min_days'])}, avg={row['avg_days']}, max={int(row['max_days'])}) | Efficiency: {row['Efficiency_Score']}%", axis=1)
                
                fig_closure = px.bar(df_closure_grouped, y='ITC', x='avg_days', text='custom_text', color='ITC', orientation='h', color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_closure.update_traces(textposition='inside', insidetextfont=dict(color='#2c3e50', size=14, family="Arial Black"), marker_line_color='rgba(0,0,0,0.1)', marker_line_width=1)
                fig_closure.update_layout(xaxis_title="Average Days to Close", yaxis_title="", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', height=350, margin=dict(l=0, r=0, t=20, b=0), showlegend=False, xaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)'), yaxis=dict(showgrid=False))
                st.plotly_chart(fig_closure, use_container_width=True)
            else:
                st.info("Not enough valid data (missing submitted dates) to plot ITC closure time.")

        with tab_itc_chart:
            df_itc = df[df.get('ITC', pd.Series()).astype(str).str.strip() != '']
            if not df_itc.empty:
                df_itc_counts = df_itc.groupby(['ITC', 'Current status']).size().reset_index(name='Count')
                fig_itc = px.bar(df_itc_counts, x='ITC', y='Count', color='Current status', text='Count', color_discrete_map=color_map)
                fig_itc.update_layout(xaxis_title="ITC Status", yaxis_title="Total Tenders", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white'))
                st.plotly_chart(fig_itc, width="stretch")

        with tab_officer_chart:
            df_officers = df[df.get('Responsible officer', pd.Series()).astype(str).str.strip() != '']
            if not df_officers.empty:
                df_off_counts = df_officers.groupby(['Responsible officer', 'Current status']).size().reset_index(name='Count')
                fig_off = px.bar(df_off_counts, x='Responsible officer', y='Count', color='Current status', text='Count', color_discrete_map=color_map)
                fig_off.update_layout(xaxis_title="Responsible Officer", yaxis_title="Total Active Tenders", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white'))
                st.plotly_chart(fig_off, width="stretch")

    st.info("💡 **Quick Guide:** Custom columns can be edited natively by clicking on them in the grid. Rows highlighted in red are overdue based on your SLA Red-Line setting.")
    
    with st.expander("➕ Add New Tender manually", expanded=False):
        with st.form("add_tender_form", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                new_t_no = st.text_input("Tender No")
                new_ref = st.text_input("Tender reference number *Required*")
                new_title = st.text_area("Title of the tender", height=100)
                new_user = st.text_input("End user")
            with c2:
                new_smt = st.date_input("SMT date/PP Planned date of publication", value=None)
                new_reason = st.text_area("Reason of approval/initiating tender", height=100)
                new_method = st.selectbox("Method of tender", METHOD_OPTIONS)
                new_officer = st.text_input("Responsible officer")
            with c3:
                new_itc = st.selectbox("ITC", ITC_OPTIONS)
                new_itc_date = st.date_input("Submitted date to ITC for TD approval", value=None)
                new_itc_com = st.text_area("Comments from ITC", height=100)
                new_status = st.selectbox("Current status", STATUS_OPTIONS)
            with c4:
                new_awarded_date = st.date_input("Date awarded", value=None)
            
            if st.form_submit_button("Save to Database", type="primary"):
                if new_ref.strip() == "":
                    st.error("⚠️ Tender reference number is required!")
                else:
                    new_row = {
                        'fiscal_year': selected_fy, 'Tender No': new_t_no, 'Tender reference number': new_ref,
                        'Title of the tender': new_title, 'End user': new_user, 'SMT date/PP Planned date of publication': new_smt.strftime('%Y-%m-%d') if new_smt else "",
                        'Reason of approval/for initiating tender': new_reason, 'Method of tender': new_method, 'Responsible officer': new_officer,
                        'ITC': new_itc, 'Submitted date to ITC for TD approval': new_itc_date.strftime('%Y-%m-%d') if new_itc_date else "",
                        'Comments from ITC': new_itc_com, 'Current status': new_status, 'Date awarded': new_awarded_date.strftime('%Y-%m-%d') if new_awarded_date else ""
                    }
                    db.upsert_tender(new_row)
                    db.log_action(f"➕ Added new tender '{new_ref}' to {selected_fy}")
                    st.success("Tender Saved!")
                    time.sleep(0.5)
                    st.rerun()

    action_container_top = st.empty()

    # --- AG-GRID CONFIGURATION ---
    gb = GridOptionsBuilder.from_dataframe(df.drop(columns=['fiscal_year'], errors='ignore'))
    gb.configure_column('id', hide=True) 
    gb.configure_column('Sub_Date', hide=True)
    gb.configure_column('Award_Date', hide=True)
    gb.configure_column('Calc_Award_Date', hide=True)
    gb.configure_column('Days_to_Close', hide=True)
    gb.configure_column('Is_Overdue', hide=True)
    
    gb.configure_default_column(wrapText=True, autoHeight=True, editable=True, minWidth=150)
    
    # 🚨 SMART HIGHLIGHTING FOR OVERDUE SLA
    gb.configure_grid_options(
        singleClickEdit=True, 
        alwaysShowVerticalScroll=True, 
        domLayout='autoHeight',
        getRowStyle=JsCode("""
        function(params) {
            if (params.data.Is_Overdue === true) {
                return {'backgroundColor': '#ffebee'}; // Soft alert red background
            }
            return null;
        }
        """)
    )
    gb.configure_selection(selection_mode="single", use_checkbox=True)
    
    rich_text_renderer = JsCode("class RichTextRenderer { init(params) { this.eGui = document.createElement('div'); this.eGui.style.whiteSpace = 'normal'; this.eGui.style.wordBreak = 'break-word'; this.eGui.innerHTML = params.value ? params.value : ''; let paragraphs = this.eGui.querySelectorAll('p'); for (let i = 0; i < paragraphs.length; i++) { paragraphs[i].style.margin = '0'; paragraphs[i].style.padding = '0'; } } getGui() { return this.eGui; } }")
    custom_date_editor = JsCode("class DatePickerEditor { init(params) { this.eInput = document.createElement('input'); this.eInput.type = 'date'; this.eInput.value = params.value || ''; this.eInput.style.width = '100%'; this.eInput.style.height = '100%'; this.eInput.style.padding = '5px'; this.eInput.style.border = 'none'; } getGui() { return this.eInput; } afterGuiAttached() { this.eInput.focus(); } getValue() { return this.eInput.value; } }")
    date_formatter = JsCode("function(params) { if (!params.value) return ''; let dateParts = params.value.split('-'); if (dateParts.length !== 3) return params.value; let year = dateParts[0]; let month = parseInt(dateParts[1], 10) - 1; let day = parseInt(dateParts[2], 10); const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']; return day + '-' + months[month] + '-' + year; }")
    rich_text_opts = {"editable": False, "cellRenderer": rich_text_renderer}
    status_cellstyle = JsCode("function(params) { if (params.value === 'Awarded') return {'backgroundColor': '#28a745', 'color': 'white', 'fontWeight': 'bold'}; if (params.value === 'Cancelled') return {'backgroundColor': '#dc3545', 'color': 'white', 'fontWeight': 'bold'}; if (params.value === 'Under Evaluation') return {'backgroundColor': '#ffc107', 'color': 'black', 'fontWeight': 'bold'}; if (params.value === 'Published') return {'backgroundColor': '#17a2b8', 'color': 'white', 'fontWeight': 'bold'}; if (params.value === 'Planned') return {'backgroundColor': '#6c757d', 'color': 'white', 'fontWeight': 'bold'}; return null; }")

    gb.configure_column('Tender No', width=120, minWidth=120, checkboxSelection=True)
    gb.configure_column('Tender reference number', width=250, minWidth=250, editable=False) 
    gb.configure_column('Title of the tender', width=400, minWidth=400, **rich_text_opts)
    gb.configure_column('Reason of approval/for initiating tender', width=400, minWidth=400, **rich_text_opts)
    gb.configure_column('Comments from ITC', width=350, minWidth=350, **rich_text_opts)
    gb.configure_column('End user', width=150, minWidth=150)
    gb.configure_column('Responsible officer', width=200, minWidth=200)
    gb.configure_column("Method of tender", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': METHOD_OPTIONS}, width=160, minWidth=160)
    gb.configure_column("ITC", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': ITC_OPTIONS}, width=120, minWidth=120)
    gb.configure_column('SMT date/PP Planned date of publication', editable=True, width=250, minWidth=250, cellEditor=custom_date_editor, valueFormatter=date_formatter)
    gb.configure_column('Submitted date to ITC for TD approval', editable=True, width=250, minWidth=250, cellEditor=custom_date_editor, valueFormatter=date_formatter)
    
    # NEW DISPLAY COLUMN FOR "DAYS TAKEN TO CLOSE"
    gb.configure_column('Date awarded', editable=True, width=200, minWidth=200, cellEditor=custom_date_editor, valueFormatter=date_formatter)
    gb.configure_column('Days taken to close', editable=False, width=150, minWidth=150)
    
    gb.configure_column("Current status", editable=True, pinned='right', cellStyle=status_cellstyle, cellEditor='agSelectCellEditor', cellEditorParams={'values': STATUS_OPTIONS}, width=160, minWidth=160)

    custom_css = {".ag-header": {"position": "sticky !important", "top": "0px !important", "z-index": "1000 !important", "background-color": "#2c3e50 !important", "border-bottom": "2px solid #1e3c72"}, ".ag-header-cell-label": {"font-weight": "bold !important", "color": "white !important", "font-size": "14px !important"}}

    grid_response = AgGrid(df, gridOptions=gb.build(), update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED, data_return_mode=DataReturnMode.AS_INPUT, fit_columns_on_grid_load=False, theme='streamlit', allow_unsafe_jscode=True, custom_css=custom_css)

    action_container_bottom = st.empty()
    selected_rows = grid_response.get("selected_rows")
    
    has_selection = False
    if isinstance(selected_rows, pd.DataFrame):
        if not selected_rows.empty:
            has_selection = True
            selected_data = selected_rows.iloc[0].to_dict()
    elif isinstance(selected_rows, list):
        if len(selected_rows) > 0:
            has_selection = True
            selected_data = selected_rows[0]

    if has_selection:
        with action_container_top.container():
            c1, c2, _ = st.columns([2, 2, 8])
            with c1:
                if st.button("✏️ Edit Selected Row ⬆️", type="primary", use_container_width=True, key="btn_edit_top"): edit_row_dialog(selected_data, selected_fy)
            with c2:
                if st.button("🗑️ Delete Selected Row ⬆️", type="secondary", use_container_width=True, key="btn_del_top"): delete_row_dialog(selected_data)
                
        with action_container_bottom.container():
            c1, c2, _ = st.columns([2, 2, 8])
            with c1:
                if st.button("✏️ Edit Selected Row ⬇️", type="primary", use_container_width=True, key="btn_edit_bot"): edit_row_dialog(selected_data, selected_fy)
            with c2:
                if st.button("🗑️ Delete Selected Row ⬇️", type="secondary", use_container_width=True, key="btn_del_bot"): delete_row_dialog(selected_data)

    # --- SQLITE SYNC FOR INLINE EDITS (Handles dynamic custom columns & robust dates) ---
    edited_df = grid_response['data']
    changes_made = False
    
    # Reverse the mapping to translate UI headers back to DB column names
    reverse_map = {v: k for k, v in db.RENAME_MAP.items()}

    for index, new_row in edited_df.iterrows():
        if 'id' not in new_row or pd.isna(new_row['id']): continue
        db_id = int(new_row['id'])
        ref_val = new_row.get('Tender reference number', '')
        
        old_row_match = df[df['id'] == db_id]
        if old_row_match.empty: continue
        old_row = old_row_match.iloc[0]
        
        for col in edited_df.columns:
            # Skip computational/hidden frontend columns
            if col in ['Is_Overdue', 'Sub_Date', 'Award_Date', 'Calc_Award_Date', 'Days_to_Close', 'Days taken to close', '_selectedRowNodeInfo']: continue
            
            # Map UI header back to DB schema (fallback to the col name itself for newly added custom columns)
            db_col = reverse_map.get(col, col) 
            
            old_val = str(old_row.get(col, "")).strip() if pd.notna(old_row.get(col, "")) else ""
            new_val = str(new_row.get(col, "")).strip() if pd.notna(new_row.get(col, "")) else ""
            
            if old_val != new_val:
                # BUG FIX: Safely parse inline date edits to avoid crashing on empty/invalid dates
                if col in ['SMT date/PP Planned date of publication', 'Submitted date to ITC for TD approval', 'Date awarded']:
                    parsed_date = pd.to_datetime(new_val, errors='coerce')
                    new_val = parsed_date.strftime('%Y-%m-%d') if pd.notna(parsed_date) else ""
                
                db.update_single_cell(db_id, db_col, new_val)
                db.log_action(f"✏️ Inline edit on '{col}' for Tender '{ref_val}' ({selected_fy})")
                changes_made = True
    
    if changes_made: st.rerun()

    # --- EXPORT CSV ---
    st.markdown("<hr/>", unsafe_allow_html=True)
    csv_export = df.drop(columns=['id', 'fiscal_year', 'Sub_Date', 'Award_Date', 'Calc_Award_Date', 'Days_to_Close', 'Is_Overdue'], errors='ignore').to_csv(index=False).encode('utf-8')
    st.download_button(label="💾 Export Dashboard to CSV", data=csv_export, file_name=f"Tenders_{selected_fy}_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

# ==========================================
# TABS 2, 3, 4: UPLOAD, LOGS, DELETED
# ==========================================
with tab_upload:
    st.subheader(f"📂 Upload Data to [{selected_fy}]")
    st.markdown("**You can now upload standard Excel (.xlsx) or CSV files.**")
    with st.form("upload_form", clear_on_submit=True):
        uploaded_file = st.file_uploader("Upload File", type=["csv", "xlsx", "xls"])
        submit_upload = st.form_submit_button("Process and Import Data", type="primary")

        if submit_upload:
            if uploaded_file is None:
                st.warning("⚠️ Please select a file first before clicking Process.")
            else:
                with st.spinner("Importing Data..."):
                    try:
                        if uploaded_file.name.endswith('.csv'):
                            try: import_df = pd.read_csv(uploaded_file)
                            except:
                                uploaded_file.seek(0)
                                import_df = pd.read_csv(uploaded_file, sep=';')
                        else: import_df = pd.read_excel(uploaded_file)
                        
                        import_df.columns = import_df.columns.str.strip()
                        import_df.dropna(how='all', inplace=True)
                        
                        rows_to_insert = []
                        
                        # BUG FIX: Helper to safely parse dates during bulk upload
                        def safe_parse_date(val):
                            dt = pd.to_datetime(str(val).strip(), errors='coerce')
                            return dt.strftime('%Y-%m-%d') if pd.notna(dt) else ""

                        for index, row in import_df.iterrows():
                            raw_ref = str(row.get('Tender reference number', '')).strip()
                            if not raw_ref or raw_ref.lower() == 'nan': raw_ref = f"N/A-{index}"
                            
                            t_no = str(row.get('Tender No', row.get('#', ''))).strip()
                            if t_no.endswith('.0'): t_no = t_no[:-2]
                            if t_no.lower() == 'nan': t_no = ""

                            clean_smt = safe_parse_date(row.get('SMT date/PP Planned date of publication', ''))
                            clean_itc_d = safe_parse_date(row.get('Submitted date to ITC for TD approval', ''))
                            clean_awd_d = safe_parse_date(row.get('Date awarded', ''))

                            raw_itc = str(row.get('ITC', '')).strip().upper().replace(" ", "")
                            clean_itc = raw_itc if raw_itc in ["ITC1", "ITC2", "ITC3", "ITC4"] else ""

                            row_dict = {
                                'fiscal_year': selected_fy, 'Tender No': t_no, 'Tender reference number': raw_ref,
                                'Title of the tender': str(row.get('Title of the tender', '')).strip() if pd.notna(row.get('Title of the tender')) else "",
                                'End user': str(row.get('End user', '')).strip() if pd.notna(row.get('End user')) else "",
                                'SMT date/PP Planned date of publication': clean_smt,
                                'Reason of approval/for initiating tender': str(row.get('Reason of approval/for initiating tender', '')).strip() if pd.notna(row.get('Reason of approval/for initiating tender')) else "",
                                'Method of tender': str(row.get('Method of tender', '')).strip() if pd.notna(row.get('Method of tender')) else "",
                                'Responsible officer': str(row.get('Responsible officer', '')).strip() if pd.notna(row.get('Responsible officer')) else "",
                                'ITC': clean_itc, 'Submitted date to ITC for TD approval': clean_itc_d,
                                'Comments from ITC': str(row.get('Comments from ITC', '')).strip() if pd.notna(row.get('Comments from ITC')) else "",
                                'Current status': str(row.get('Current status', '')).strip() if pd.notna(row.get('Current status')) else "",
                                'Date awarded': clean_awd_d
                            }
                            rows_to_insert.append(row_dict)
                        
                        if rows_to_insert: db.upsert_tenders_bulk(rows_to_insert)
                        db.log_action(f"📁 Bulk uploaded {len(rows_to_insert)} tenders into {selected_fy}.")
                        st.success(f"Successfully processed {len(rows_to_insert)} tenders!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error processing file: {e}. Please ensure it is a valid Excel or CSV file matching the required headers.")

with tab_logs:
    st.subheader("📝 Edit Trail & Activity Logs")
    logs_df = db.get_logs()
    if not logs_df.empty:
        st.dataframe(logs_df, hide_index=True, width="stretch", column_config={"timestamp": st.column_config.TextColumn("Time of Change", width="medium"), "message": st.column_config.TextColumn("Action/Modification", width="large")})

with tab_deleted:
    st.subheader(f"🗑️ Deleted Tenders for [{selected_fy}]")
    deleted_df = db.get_deleted_tenders(selected_fy)
    if deleted_df.empty:
        st.info("There are currently no deleted records in this fiscal year.")
    else:
        st.metric("Total Deleted Records", len(deleted_df))
        st.dataframe(deleted_df[['id', 'Tender No', 'Tender reference number', 'Title of the tender', 'Deleted By', 'Deleted At']], hide_index=True, width="stretch", column_config={"id": None, "Deleted At": st.column_config.TextColumn("Time of Deletion", width="medium")})