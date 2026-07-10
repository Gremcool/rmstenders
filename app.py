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

# --- DROPDOWN OPTIONS ---
METHOD_OPTIONS = ["", "NCB", "ICB", "RFQ", "Direct Procurement", "Framework", "Other"]
ITC_OPTIONS = ["", "ITC1", "ITC2", "ITC3", "ITC4"]
STATUS_OPTIONS = ["", "Planned", "Draft", "Published", "Under Evaluation", "Awarded", "Cancelled"]

# --- POP-UP DIALOG FOR RICH TEXT EDITING ---
@st.dialog("✏️ Edit Tender Details", width="large")
def edit_row_dialog(row_data, active_fy):
    st.markdown(f"**Editing Tender Ref:** `{row_data.get('Tender reference number', 'N/A')}`")
    
    status_idx = STATUS_OPTIONS.index(row_data.get("Current status", "")) if row_data.get("Current status") in STATUS_OPTIONS else 0
    method_idx = METHOD_OPTIONS.index(row_data.get("Method of tender", "")) if row_data.get("Method of tender") in METHOD_OPTIONS else 0
    
    raw_itc = str(row_data.get("ITC", "")).strip().upper().replace(" ", "")
    itc_idx = ITC_OPTIONS.index(raw_itc) if raw_itc in ITC_OPTIONS else 0

    raw_smt = row_data.get("SMT date/PP Planned date of publication", "")
    try: default_smt = pd.to_datetime(raw_smt).date() if pd.notna(raw_smt) and str(raw_smt).strip() != "" else None
    except: default_smt = None

    raw_itc_date = row_data.get("Submitted date to ITC for TD approval", "")
    try: default_itc_date = pd.to_datetime(raw_itc_date).date() if pd.notna(raw_itc_date) and str(raw_itc_date).strip() != "" else None
    except: default_itc_date = None

    c1, c2, c3 = st.columns(3)
    with c1:
        new_t_no = st.text_input("Tender No", value=row_data.get("Tender No", ""))
        new_user = st.text_input("End user", value=row_data.get("End user", ""))
        new_status = st.selectbox("Current status", STATUS_OPTIONS, index=status_idx)
    with c2:
        new_smt = st.date_input("SMT date / Planned date", value=default_smt)
        new_method = st.selectbox("Method of tender", METHOD_OPTIONS, index=method_idx)
        new_officer = st.text_input("Responsible officer", value=row_data.get("Responsible officer", ""))
    with c3:
        new_itc = st.selectbox("ITC", ITC_OPTIONS, index=itc_idx)
        new_itc_date = st.date_input("Date submitted to ITC", value=default_itc_date)

    st.divider()
    
    st.markdown("### 📝 Title of the tender")
    new_title = st_quill(value=row_data.get("Title of the tender", ""), placeholder="Write title here...", html=True, key="quill_title")
    
    st.markdown("### 📋 Reason of approval / for initiating tender")
    new_reason = st_quill(value=row_data.get("Reason of approval/for initiating tender", ""), placeholder="Write reason here...", html=True, key="quill_reason")
    
    st.markdown("### 💬 Comments from ITC")
    new_itc_com = st_quill(value=row_data.get("Comments from ITC", ""), placeholder="Write comments here...", html=True, key="quill_itc_com")
    
    # Updated to width="stretch"
    if st.button("Save Changes", type="primary", width="stretch"):
        updated_row = {
            'fiscal_year': active_fy,
            'Tender No': new_t_no,
            'Tender reference number': row_data.get("Tender reference number", ""),
            'Title of the tender': new_title,
            'End user': new_user,
            'SMT date/PP Planned date of publication': new_smt.strftime('%Y-%m-%d') if new_smt else "",
            'Reason of approval/for initiating tender': new_reason,
            'Method of tender': new_method,
            'Responsible officer': new_officer,
            'ITC': new_itc,
            'Submitted date to ITC for TD approval': new_itc_date.strftime('%Y-%m-%d') if new_itc_date else "",
            'Comments from ITC': new_itc_com,
            'Current status': new_status
        }
        db.upsert_tender(updated_row)
        db.log_action(f"✏️ Rich-text update made to tender: '{updated_row['Tender reference number']}'")
        st.success("Changes Saved!")
        time.sleep(0.5)
        st.rerun()

# --- HEADER & FISCAL YEAR MANAGEMENT ---
col_logo, col_title = st.columns([1, 15])
with col_logo:
    if os.path.exists("logo.jpg"):
        # Updated to width="stretch"
        st.image("logo.jpg", width="stretch")
    else:
        st.markdown("<h1 style='text-align: center; margin: 0;'>🏢</h1>", unsafe_allow_html=True)

with col_title:
    st.markdown("<div class='custom-title'>RMS PROCUREMENT TENDER TRACKER</div>", unsafe_allow_html=True)
    st.markdown("<div class='custom-subtitle'>Monitor fair allocation and track tender statuses across fiscal years.</div>", unsafe_allow_html=True)
st.markdown("<hr style='margin-top: 15px; margin-bottom: 15px; border: 0; border-top: 1px solid #eee;' />", unsafe_allow_html=True)

fiscal_years = db.get_fiscal_years()

col_fy1, col_fy2 = st.columns([1, 1])
with col_fy1:
    selected_fy = st.selectbox("📂 Active Fiscal Year Dashboard", fiscal_years)
with col_fy2:
    with st.expander("➕ Create New Fiscal Year Workspace"):
        new_fy = st.text_input("Enter Year (e.g., 2026-2027)")
        if st.button("Initialize Year"):
            if new_fy and new_fy not in fiscal_years:
                db.add_fiscal_year(new_fy.strip())
                st.success(f"Workspace {new_fy} created!")
                st.rerun()
            else:
                st.error("Invalid or duplicate year.")

st.markdown("<hr style='margin-top: 15px; margin-bottom: 15px; border: 0; border-top: 1px solid #eee;' />", unsafe_allow_html=True)

# --- TABS ---
tab_tracker, tab_upload, tab_logs = st.tabs(["📊 Tender Tracker & Analytics", "📂 Upload Data", "📝 Edit Trail"])

# ==========================================
# TAB 1: THE MAIN TRACKER
# ==========================================
with tab_tracker:
    df = db.load_data(selected_fy)
    
    if df.empty:
        st.warning(f"📭 No tenders found for {selected_fy}. Upload an Excel/CSV file or add manually.")
    else:
        if 'Tender No' in df.columns:
            df['Tender No'] = df['Tender No'].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', '')

        for col in ['SMT date/PP Planned date of publication', 'Submitted date to ITC for TD approval']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')

        # --- ANALYTICS & KPIs ---
        total_tenders = len(df)
        awarded = len(df[df["Current status"] == "Awarded"])
        evaluation = len(df[df["Current status"] == "Under Evaluation"])
        published = len(df[df["Current status"] == "Published"])
        planned = len(df[df["Current status"] == "Planned"])

        met1, met2, met3, met4, met5 = st.columns(5)
        with met1: st.markdown(create_kpi_card("Total Tenders", total_tenders, "#f8f9fa", "#2c3e50", "#e9ecef"), unsafe_allow_html=True)
        with met2: st.markdown(create_kpi_card("Awarded ✅", awarded, "#d4edda", "#155724", "#c3e6cb"), unsafe_allow_html=True)
        with met3: st.markdown(create_kpi_card("Evaluation 🔄", evaluation, "#fff3cd", "#856404", "#ffeeba"), unsafe_allow_html=True)
        with met4: st.markdown(create_kpi_card("Published 📢", published, "#cce5ff", "#004085", "#b8daff"), unsafe_allow_html=True)
        with met5: st.markdown(create_kpi_card("Planned ⏳", planned, "#e2e3e5", "#383d41", "#d6d8db"), unsafe_allow_html=True)

        with st.expander("📈 View Analytics & Allocation Charts", expanded=False):
            tab_itc_chart, tab_officer_chart = st.tabs(["📊 ITC Status Distribution", "📊 Officer Workload Allocation"])
            
            color_map = {
                'Awarded': '#28a745', 
                'Cancelled': '#dc3545', 
                'Under Evaluation': '#ffc107', 
                'Published': '#17a2b8', 
                'Planned': '#6c757d',
                'Draft': '#adb5bd'
            }

            with tab_itc_chart:
                df_itc = df[df['ITC'].astype(str).str.strip() != '']
                if not df_itc.empty:
                    df_itc_counts = df_itc.groupby(['ITC', 'Current status']).size().reset_index(name='Count')
                    if not df_itc_counts.empty:
                        fig_itc = px.bar(
                            df_itc_counts, x='ITC', y='Count', color='Current status', 
                            text='Count', color_discrete_map=color_map
                        )
                        fig_itc.update_layout(
                            xaxis_title="ITC Status", yaxis_title="Total Tenders",
                            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white')
                        )
                        # Updated to width="stretch"
                        st.plotly_chart(fig_itc, width="stretch")
                    else:
                        st.info("Not enough valid data to plot ITC distribution.")
                else:
                    st.info("No ITC assignments available to visualize.")

            with tab_officer_chart:
                df_officers = df[df['Responsible officer'].astype(str).str.strip() != '']
                if not df_officers.empty:
                    df_off_counts = df_officers.groupby(['Responsible officer', 'Current status']).size().reset_index(name='Count')
                    if not df_off_counts.empty:
                        fig_off = px.bar(
                            df_off_counts, x='Responsible officer', y='Count', color='Current status', 
                            text='Count', color_discrete_map=color_map
                        )
                        fig_off.update_layout(
                            xaxis_title="Responsible Officer", yaxis_title="Total Active Tenders",
                            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white')
                        )
                        # Updated to width="stretch"
                        st.plotly_chart(fig_off, width="stretch")
                    else:
                        st.info("Not enough valid data to plot Officer allocation.")
                else:
                    st.info("No Responsible Officers assigned yet.")

        st.info("💡 **Quick Guide:** Click any cell to inline edit! Empty Date and Status cells now have quick-pickers.")
        
        with st.expander("➕ Add New Tender manually", expanded=False):
            with st.form("add_tender_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
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
                
                if st.form_submit_button("Save to Database", type="primary"):
                    if new_ref.strip() == "":
                        st.error("⚠️ Tender reference number is required!")
                    else:
                        new_row = {
                            'fiscal_year': selected_fy,
                            'Tender No': new_t_no,
                            'Tender reference number': new_ref,
                            'Title of the tender': new_title,
                            'End user': new_user,
                            'SMT date/PP Planned date of publication': new_smt.strftime('%Y-%m-%d') if new_smt else "",
                            'Reason of approval/for initiating tender': new_reason,
                            'Method of tender': new_method,
                            'Responsible officer': new_officer,
                            'ITC': new_itc,
                            'Submitted date to ITC for TD approval': new_itc_date.strftime('%Y-%m-%d') if new_itc_date else "",
                            'Comments from ITC': new_itc_com,
                            'Current status': new_status
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
        
        gb.configure_default_column(wrapText=True, autoHeight=True, editable=True)
        gb.configure_grid_options(singleClickEdit=True, alwaysShowVerticalScroll=True, domLayout='autoHeight')
        gb.configure_selection(selection_mode="single", use_checkbox=True)
        
        rich_text_renderer = JsCode("""
        class RichTextRenderer {
            init(params) {
                this.eGui = document.createElement('div');
                this.eGui.style.whiteSpace = 'normal';
                this.eGui.style.wordBreak = 'break-word';
                this.eGui.innerHTML = params.value ? params.value : '';
                
                let paragraphs = this.eGui.querySelectorAll('p');
                for (let i = 0; i < paragraphs.length; i++) {
                    paragraphs[i].style.margin = '0';
                    paragraphs[i].style.padding = '0';
                }
            }
            getGui() { return this.eGui; }
        }
        """)
        
        custom_date_editor = JsCode("""
        class DatePickerEditor {
            init(params) {
                this.eInput = document.createElement('input');
                this.eInput.type = 'date';
                this.eInput.value = params.value || '';
                this.eInput.style.width = '100%';
                this.eInput.style.height = '100%';
                this.eInput.style.padding = '5px';
                this.eInput.style.border = 'none';
            }
            getGui() { return this.eInput; }
            afterGuiAttached() { this.eInput.focus(); }
            getValue() { return this.eInput.value; }
        }
        """)

        date_formatter = JsCode("""
        function(params) {
            if (!params.value) return '';
            let dateParts = params.value.split('-');
            if (dateParts.length !== 3) return params.value;
            let year = dateParts[0];
            let month = parseInt(dateParts[1], 10) - 1;
            let day = parseInt(dateParts[2], 10);
            const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
            return day + '-' + months[month] + '-' + year;
        }
        """)

        rich_text_opts = {"editable": False, "cellRenderer": rich_text_renderer}

        gb.configure_column('Tender No', width=120)
        gb.configure_column('Tender reference number', width=300, editable=False) 
        gb.configure_column('Title of the tender', width=450, **rich_text_opts)
        gb.configure_column('Reason of approval/for initiating tender', width=450, **rich_text_opts)
        gb.configure_column('Comments from ITC', width=350, **rich_text_opts)
        gb.configure_column('End user', width=160)
        gb.configure_column('Responsible officer', width=220)
        
        gb.configure_column("Method of tender", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': METHOD_OPTIONS}, width=160)
        gb.configure_column("ITC", editable=True, cellEditor='agSelectCellEditor', cellEditorParams={'values': ITC_OPTIONS}, width=120)
        
        gb.configure_column('SMT date/PP Planned date of publication', editable=True, width=250, cellEditor=custom_date_editor, valueFormatter=date_formatter)
        gb.configure_column('Submitted date to ITC for TD approval', editable=True, width=250, cellEditor=custom_date_editor, valueFormatter=date_formatter)
        
        status_cellstyle = JsCode("""
        function(params) {
            if (params.value === 'Awarded') return {'backgroundColor': '#28a745', 'color': 'white', 'fontWeight': 'bold'};
            if (params.value === 'Cancelled') return {'backgroundColor': '#dc3545', 'color': 'white', 'fontWeight': 'bold'};
            if (params.value === 'Under Evaluation') return {'backgroundColor': '#ffc107', 'color': 'black', 'fontWeight': 'bold'};
            if (params.value === 'Published') return {'backgroundColor': '#17a2b8', 'color': 'white', 'fontWeight': 'bold'};
            if (params.value === 'Planned') return {'backgroundColor': '#6c757d', 'color': 'white', 'fontWeight': 'bold'};
            return null;
        }
        """)
        
        gb.configure_column("Current status", editable=True, pinned='right', cellStyle=status_cellstyle, cellEditor='agSelectCellEditor', cellEditorParams={'values': STATUS_OPTIONS}, width=160)

        custom_css = {
            ".ag-root-wrapper": {"overflow": "visible !important"},
            ".ag-root-wrapper-body": {"overflow": "visible !important"},
            ".ag-root": {"overflow": "visible !important"},
            ".ag-header": {
                "position": "sticky !important",
                "top": "0px !important",
                "z-index": "1000 !important",
                "background-color": "#2c3e50 !important",
                "border-bottom": "2px solid #1e3c72"
            },
            ".ag-header-cell-label": {"font-weight": "bold !important", "color": "white !important", "font-size": "14px !important"}
        }

        grid_response = AgGrid(
            df, gridOptions=gb.build(), update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            data_return_mode=DataReturnMode.AS_INPUT, fit_columns_on_grid_load=False,
            theme='streamlit', allow_unsafe_jscode=True, custom_css=custom_css
        )

        action_container_bottom = st.empty()

        selected_rows = grid_response.get("selected_rows")
        if selected_rows is not None and len(selected_rows) > 0:
            if isinstance(selected_rows, pd.DataFrame):
                selected_data = selected_rows.iloc[0].to_dict()
            else:
                selected_data = selected_rows[0]
                
            with action_container_top:
                if st.button("✏️ Edit Selected Row ⬆️", type="primary", key="btn_edit_top"):
                    edit_row_dialog(selected_data, selected_fy)
                    
            with action_container_bottom:
                if st.button("✏️ Edit Selected Row ⬇️", type="primary", key="btn_edit_bot"):
                    edit_row_dialog(selected_data, selected_fy)

        # --- SQLITE SYNC FOR INLINE EDITS ---
        edited_df = grid_response['data']
        changes_made = False
        
        db_col_map = {
            'Tender No': 'tender_no',
            'End user': 'end_user',
            'SMT date/PP Planned date of publication': 'smt_date',
            'Method of tender': 'method', 
            'Responsible officer': 'responsible_officer',
            'ITC': 'itc',
            'Submitted date to ITC for TD approval': 'itc_submitted_date',
            'Current status': 'status'
        }

        for index, new_row in edited_df.iterrows():
            if 'id' not in new_row:
                continue
                
            db_id = int(new_row['id'])
            ref_val = new_row['Tender reference number']
            
            old_row_match = df[df['id'] == db_id]
            if old_row_match.empty:
                continue
            old_row = old_row_match.iloc[0]
            
            for col in db_col_map.keys():
                if col in edited_df.columns:
                    old_val = str(old_row[col]).strip() if pd.notna(old_row[col]) else ""
                    new_val = str(new_row[col]).strip() if pd.notna(new_row[col]) else ""
                    
                    if old_val != new_val:
                        if col in ['SMT date/PP Planned date of publication', 'Submitted date to ITC for TD approval']:
                            try: new_val = pd.to_datetime(new_val).strftime('%Y-%m-%d')
                            except: new_val = ""
                        
                        db.update_single_cell(db_id, db_col_map[col], new_val)
                        db.log_action(f"✏️ Inline edit on '{col}' for Tender '{ref_val}' ({selected_fy})")
                        changes_made = True
        
        if changes_made: st.rerun()

        # --- EXPORT CSV ---
        st.markdown("<hr/>", unsafe_allow_html=True)
        csv_export = df.drop(columns=['id', 'fiscal_year'], errors='ignore').to_csv(index=False).encode('utf-8')
        st.download_button(label="💾 Export Dashboard to CSV", data=csv_export, file_name=f"Tenders_{selected_fy}_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

# ==========================================
# TAB 2: UPLOAD CSV / EXCEL
# ==========================================
with tab_upload:
    st.subheader(f"📂 Upload Data to [{selected_fy}]")
    st.markdown("""
    **You can now upload standard Excel (.xlsx) or CSV files.**
    Must have exact column headers: `Tender No` (or `#`), `Tender reference number`, `Title of the tender`, `End user`, `SMT date/PP Planned date of publication`, `Reason of approval/for initiating tender`, `Method of tender`, `Responsible officer`, `ITC`, `Submitted date to ITC for TD approval`, `Comments from ITC`, `Current status`
    """)

    uploaded_file = st.file_uploader("Upload File", type=["csv", "xlsx", "xls"])

    if uploaded_file is not None:
        if st.button("Process and Import Data", type="primary"):
            with st.spinner("Importing Data..."):
                try:
                    if uploaded_file.name.endswith('.csv'):
                        import_df = pd.read_csv(uploaded_file, sep=None, engine='python')
                    else:
                        import_df = pd.read_excel(uploaded_file)
                    
                    import_df.columns = import_df.columns.str.strip()
                    import_df.dropna(how='all', inplace=True)
                    
                    rows_added = 0
                    for index, row in import_df.iterrows():
                        raw_ref = str(row.get('Tender reference number', '')).strip()
                        if not raw_ref or raw_ref.lower() == 'nan':
                            raw_ref = f"N/A-{index}"
                        
                        t_no = str(row.get('Tender No', row.get('#', ''))).strip()
                        if t_no.endswith('.0'): t_no = t_no[:-2]
                        if t_no.lower() == 'nan': t_no = ""

                        raw_smt = str(row.get('SMT date/PP Planned date of publication', '')).strip()
                        try: clean_smt = pd.to_datetime(raw_smt).strftime('%Y-%m-%d') if raw_smt and raw_smt.lower() != 'nan' else ""
                        except: clean_smt = ""
                        
                        raw_itc_d = str(row.get('Submitted date to ITC for TD approval', '')).strip()
                        try: clean_itc_d = pd.to_datetime(raw_itc_d).strftime('%Y-%m-%d') if raw_itc_d and raw_itc_d.lower() != 'nan' else ""
                        except: clean_itc_d = ""

                        raw_itc = str(row.get('ITC', '')).strip().upper().replace(" ", "")
                        clean_itc = raw_itc if raw_itc in ["ITC1", "ITC2", "ITC3", "ITC4"] else ""

                        row_dict = {
                            'fiscal_year': selected_fy,
                            'Tender No': t_no,
                            'Tender reference number': raw_ref,
                            'Title of the tender': str(row.get('Title of the tender', '')).strip() if pd.notna(row.get('Title of the tender')) else "",
                            'End user': str(row.get('End user', '')).strip() if pd.notna(row.get('End user')) else "",
                            'SMT date/PP Planned date of publication': clean_smt,
                            'Reason of approval/for initiating tender': str(row.get('Reason of approval/for initiating tender', '')).strip() if pd.notna(row.get('Reason of approval/for initiating tender')) else "",
                            'Method of tender': str(row.get('Method of tender', '')).strip() if pd.notna(row.get('Method of tender')) else "",
                            'Responsible officer': str(row.get('Responsible officer', '')).strip() if pd.notna(row.get('Responsible officer')) else "",
                            'ITC': clean_itc,
                            'Submitted date to ITC for TD approval': clean_itc_d,
                            'Comments from ITC': str(row.get('Comments from ITC', '')).strip() if pd.notna(row.get('Comments from ITC')) else "",
                            'Current status': str(row.get('Current status', '')).strip() if pd.notna(row.get('Current status')) else ""
                        }
                        
                        db.upsert_tender(row_dict)
                        rows_added += 1
                    
                    db.log_action(f"📁 Bulk uploaded {rows_added} tenders into {selected_fy}.")
                    st.success(f"Successfully processed {rows_added} tenders into Fiscal Year {selected_fy}!")
                    
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error processing file: {e}. Please ensure it is a valid Excel or CSV file matching the required headers.")

# ==========================================
# TAB 3: MODIFICATION LOGS
# ==========================================
with tab_logs:
    st.subheader("📝 Edit Trail & Activity Logs")
    st.markdown("Persistent audit trail of all manual edits, uploads, and system changes.")
    
    logs_df = db.get_logs()
    
    if not logs_df.empty:
        # Updated to width="stretch"
        st.dataframe(
            logs_df, 
            hide_index=True, 
            width="stretch",
            column_config={
                "timestamp": st.column_config.TextColumn("Time of Change", width="medium"),
                "message": st.column_config.TextColumn("Action/Modification", width="large")
            }
        )
    else:
        st.info("No modifications have been logged yet.")