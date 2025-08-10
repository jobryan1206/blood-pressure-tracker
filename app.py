import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime

# ---------- Config ----------
st.set_page_config(page_title="Blood Pressure Logger", page_icon="🩺", layout="wide")
st.title("🩺 Blood Pressure Logger")
st.caption("Log BP readings, add notes, and visualize trends. Writes to Google Sheets if configured; otherwise uses a local CSV.")

CSV_PATH = "bp_data.csv"
DEFAULT_SHEET_NAME = "bp_data"

# ---------- Optional Google Sheets deps ----------
try:
    import gspread
    from google.oauth2.service_account import Credentials
    from gspread_dataframe import set_with_dataframe, get_as_dataframe
except Exception:
    gspread = None
    Credentials = None

# ---------- Secrets helpers ----------
def _get_sa_secrets():
    # allow either [gcp_service_account] (BP app) or [google] (other apps)
    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])
    if "google" in st.secrets:
        return dict(st.secrets["google"])
    return None

def _gs_enabled():
    return (gspread is not None) and (_get_sa_secrets() is not None)

def get_gs_client():
    sa_info = _get_sa_secrets()
    if not sa_info:
        return None, "No Google credentials found in secrets."
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        client = gspread.authorize(creds)
        return client, None
    except Exception as e:
        return None, f"Google auth failed: {e}"

def get_sheet_handles():
    client, err = get_gs_client()
    if not client:
        return None, None, err

    sheet_ref = st.secrets.get("spreadsheet", "")
    ws_name = st.secrets.get("worksheet", DEFAULT_SHEET_NAME)

    try:
        if sheet_ref:
            if "http://" in sheet_ref or "https://" in sheet_ref:
                sh = client.open_by_url(sheet_ref)
            else:
                sh = client.open_by_key(sheet_ref)
        else:
            sh = client.create("Blood Pressure Logger Data")
        try:
            ws = sh.worksheet(ws_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=ws_name, rows=1000, cols=20)
            ws.update([["timestamp","systolic","diastolic","pulse","notes","category","map","pulse_pressure"]])
        return sh, ws, None
    except Exception as e:
        return None, None, f"Opening spreadsheet failed: {e}"

# ---------- Domain ----------
def categorize_bp(sys, dia):
    if sys < 120 and dia < 80:
        return "Normal"
    if 120 <= sys < 130 and dia < 80:
        return "Elevated"
    if (130 <= sys < 140) or (80 <= dia < 90):
        return "Hypertension Stage 1"
    if sys >= 140 or dia >= 90:
        return "Hypertension Stage 2"
    return "Uncategorized"

# ---------- IO: CSV ----------
def load_data_local():
    try:
        df = pd.read_csv(CSV_PATH, parse_dates=["timestamp"])
        for c in ["systolic","diastolic","pulse","map","pulse_pressure"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["timestamp"])
    except FileNotFoundError:
        cols = ["timestamp","systolic","diastolic","pulse","notes","category","map","pulse_pressure"]
        return pd.DataFrame(columns=cols)

def save_data_local(df):
    df.to_csv(CSV_PATH, index=False)

# ---------- IO: Google Sheets ----------
def load_data_gsheets():
    sh, ws, err = get_sheet_handles()
    if err or not ws:
        return None, err
    try:
        df = get_as_dataframe(ws, evaluate_formulas=True, header=0, dtype=None, nrows=None).dropna(how="all")
        if df.empty:
            df = pd.DataFrame(columns=["timestamp","systolic","diastolic","pulse","notes","category","map","pulse_pressure"])
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        for c in ["systolic","diastolic","pulse","map","pulse_pressure"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["timestamp"]), None
    except Exception as e:
        return None, f"Read from Google Sheets failed: {e}"

def save_data_gsheets(df):
    sh, ws, err = get_sheet_handles()
    if err or not ws:
        return err or "No worksheet"
    try:
        cols = ["timestamp","systolic","diastolic","pulse","notes","category","map","pulse_pressure"]
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols]
        if pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        ws.clear()
        set_with_dataframe(ws, df, include_index=False, include_column_header=True, resize=True)
        return None
    except Exception as e:
        return f"Write to Google Sheets failed: {e}"

# ---------- IO: router ----------
def load_data():
    if _gs_enabled():
        df, err = load_data_gsheets()
        if err:
            st.warning(f"Google Sheets read issue: {err} — falling back to local CSV.")
            return load_data_local(), "local"
        return df, "gsheets"
    return load_data_local(), "local"

def save_data(df, target_hint):
    if target_hint == "gsheets" and _gs_enabled():
        err = save_data_gsheets(df)
        if err:
            st.error(err)
            st.info("Saving locally instead.")
            save_data_local(df)
            return "local"
        return "gsheets"
    save_data_local(df)
    return "local"

def add_entry(sys, dia, pulse, notes, ts, target_hint):
    df, _ = load_data()
    pp = sys - dia
    row = {
        "timestamp": pd.to_datetime(ts),
        "systolic": int(sys),
        "diastolic": int(dia),
        "pulse": int(pulse) if pulse is not None else None,
        "notes": notes or "",
        "category": categorize_bp(sys, dia),
        "map": round(dia + pp/3, 1),
        "pulse_pressure": pp,
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True).sort_values("timestamp")
    used = save_data(df, target_hint)
    return df, used

def df_download_bytes(df):
    out = BytesIO()
    df.to_csv(out, index=False)
    out.seek(0)
    return out

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Data")
    io_mode = "gsheets" if _gs_enabled() else "local"
    if io_mode == "gsheets":
        st.success("Google Sheets: enabled")
        st.write(f"Worksheet: `{st.secrets.get('worksheet', DEFAULT_SHEET_NAME)}`")
        st.caption(f"Spreadsheet: {st.secrets.get('spreadsheet','auto-created or by key')}")
    else:
        st.warning("Using local CSV (Google Sheets not configured). Data is saved to `bp_data.csv`.")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("⬇️ Download CSV"):
            df_tmp, _ = load_data()
            st.download_button("Save file", data=df_download_bytes(df_tmp), file_name="bp_data.csv", mime="text/csv")
    with col_b:
        uploaded = st.file_uploader("Restore/merge from CSV", type=["csv"], label_visibility="collapsed")
        if uploaded is not None:
            try:
                existing, _ = load_data()
                incoming = pd.read_csv(uploaded, parse_dates=["timestamp"])
                merged = pd.concat([existing, incoming], ignore_index=True).drop_duplicates().sort_values("timestamp")
                used = save_data(merged, io_mode)
                st.success(f"Imported {len(incoming)} rows. Total rows: {len(merged)}. Saved to {used}.")
            except Exception as e:
                st.error(f"Import failed: {e}")

    if st.button("🗑️ Clear ALL data"):
        empty = pd.DataFrame(columns=["timestamp","systolic","diastolic","pulse","notes","category","map","pulse_pressure"])
        used = save_data(empty, io_mode)
        st.warning(f"All data cleared. Saved to {used}.")

st.divider()

# ---------- Form ----------
st.subheader("Add a reading")
with st.form("bp_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns([1,1,1,2])
    with col1:
        systolic = st.number_input("Systolic (mmHg)", min_value=50, max_value=260, value=120, step=1)
    with col2:
        diastolic = st.number_input("Diastolic (mmHg)", min_value=30, max_value=180, value=75, step=1)
    with col3:
        pulse = st.number_input("Pulse (bpm)", min_value=20, max_value=220, value=70, step=1)
    with col4:
        notes = st.text_input("Notes (optional)", placeholder="Medication, posture, time since coffee, etc.")
    manual_ts = st.checkbox("Set custom date & time")
    if manual_ts:
        c1, c2 = st.columns(2)
        with c1:
            date = st.date_input("Date", value=datetime.now().date())
        with c2:
            time = st.time_input("Time", value=datetime.now().time().replace(microsecond=0))
        ts = datetime.combine(date, time)
    else:
        ts = datetime.now()
    submitted = st.form_submit_button("Add reading", type="primary")
    if submitted:
        df, target_used = add_entry(systolic, diastolic, pulse, notes, ts, "gsheets")
        st.success(f"Reading saved to {target_used}.")
    else:
        df, _ = load_data()

# ---------- Table ----------
st.subheader("Recent readings")
if df.empty:
    st.info("No data yet. Add your first reading above.")
else:
    df_view = df.sort_values("timestamp", ascending=False).copy()
    df_view["timestamp"] = df_view["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(df_view.head(25), use_container_width=True)

# ---------- Charts ----------
if not df.empty:
    st.subheader("Trends")

    if "timestamp" not in df.columns:
        st.warning("No 'timestamp' column found yet.")
    else:
        df_plot = df.copy().sort_values("timestamp")
        df_plot.set_index("timestamp", inplace=True)

        # 7-day rolling averages
        for col in ["systolic", "diastolic"]:
            if col in df_plot.columns:
                df_plot[f"{col}_7d_avg"] = df_plot[col].rolling("7D").mean()

        st.markdown("**Systolic & Diastolic over time** (with 7-day rolling average)")
        fig1, ax1 = plt.subplots()
        if "systolic" in df_plot.columns: ax1.plot(df_plot.index, df_plot["systolic"], label="Systolic")
        if "diastolic" in df_plot.columns: ax1.plot(df_plot.index, df_plot["diastolic"], label="Diastolic")
        if "systolic_7d_avg" in df_plot.columns: ax1.plot(df_plot.index, df_plot["systolic_7d_avg"], linestyle="--", label="Systolic (7d avg)")
        if "diastolic_7d_avg" in df_plot.columns: ax1.plot(df_plot.index, df_plot["diastolic_7d_avg"], linestyle="--", label="Diastolic (7d avg)")
        ax1.set_xlabel("Date"); ax1.set_ylabel("mmHg"); ax1.legend()
        st.pyplot(fig1)

        st.markdown("**Systolic vs Diastolic** (each point = a reading)")
        fig2, ax2 = plt.subplots()
        ax2.scatter(df["systolic"], df["diastolic"])
        ax2.set_xlabel("Systolic (mmHg)"); ax2.set_ylabel("Diastolic (mmHg)")
        st.pyplot(fig2)

