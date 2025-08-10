import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime

# =========================
# App config
# =========================
st.set_page_config(page_title="Blood Pressure Logger", page_icon="💕", layout="wide")
st.title("💕 V's Blood Pressure")

CSV_PATH = "bp_data.csv"
DEFAULT_SHEET_NAME = "bp_data"
DATA_COLUMNS = ["timestamp", "systolic", "diastolic", "notes", "category", "map"]

# =========================
# Optional Google Sheets deps
# =========================
try:
    import gspread
    from google.oauth2.service_account import Credentials
    from gspread_dataframe import set_with_dataframe, get_as_dataframe
except Exception:
    gspread = None
    Credentials = None

# =========================
# Secrets + Sheets helpers
# =========================
def _get_sa_secrets():
    # Allow either [gcp_service_account] (this app) or [google] (some older apps)
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
            ws.update([DATA_COLUMNS])
        return sh, ws, None
    except Exception as e:
        return None, None, f"Opening spreadsheet failed: {e}"

# =========================
# Domain helpers
# =========================
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

def parse_int(field_label, raw, min_v, max_v):
    """Return (value:int|None, error_msg:str|None)."""
    if raw is None or str(raw).strip() == "":
        return None, f"{field_label} is required."
    try:
        val = int(str(raw).strip())
    except ValueError:
        return None, f"{field_label} must be a whole number."
    if not (min_v <= val <= max_v):
        return None, f"{field_label} must be between {min_v} and {max_v}."
    return val, None

# =========================
# IO: Local CSV
# =========================
def load_data_local():
    try:
        df = pd.read_csv(CSV_PATH, parse_dates=["timestamp"])
        for c in ["systolic", "diastolic", "map", "pulse_pressure"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["timestamp"])
    except FileNotFoundError:
        return pd.DataFrame(columns=DATA_COLUMNS)

def save_data_local(df: pd.DataFrame):
    df.to_csv(CSV_PATH, index=False)

# =========================
# IO: Google Sheets
# =========================
def load_data_gsheets():
    sh, ws, err = get_sheet_handles()
    if err or not ws:
        return None, err
    try:
        df = get_as_dataframe(ws, evaluate_formulas=True, header=0, dtype=None, nrows=None).dropna(how="all")
        if df.empty:
            df = pd.DataFrame(columns=DATA_COLUMNS)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        for c in ["systolic", "diastolic", "map", "pulse_pressure"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        # Ensure expected columns exist
        for c in DATA_COLUMNS:
            if c not in df.columns:
                df[c] = None
        return df.dropna(subset=["timestamp"]), None
    except Exception as e:
        return None, f"Read from Google Sheets failed: {e}"

def save_data_gsheets(df: pd.DataFrame):
    sh, ws, err = get_sheet_handles()
    if err or not ws:
        return err or "No worksheet"
    try:
        df2 = df.copy()
        # Ensure column order & presence
        for c in DATA_COLUMNS:
            if c not in df2.columns:
                df2[c] = None
        df2 = df2[DATA_COLUMNS]
        if pd.api.types.is_datetime64_any_dtype(df2["timestamp"]):
            df2["timestamp"] = df2["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        ws.clear()
        set_with_dataframe(ws, df2, include_index=False, include_column_header=True, resize=True)
        return None
    except Exception as e:
        return f"Write to Google Sheets failed: {e}"

# Router
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

def add_entry(sys, dia, notes, ts, target_hint):
    df, _ = load_data()
    pp = sys - dia
    row = {
        "timestamp": pd.to_datetime(ts),
        "systolic": int(sys),
        "diastolic": int(dia),
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

# =========================
# Sidebar
# =========================
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
        empty = pd.DataFrame(columns=DATA_COLUMNS)
        used = save_data(empty, io_mode)
        st.warning(f"All data cleared. Saved to {used}.")

st.divider()

# =========================
# Form (blank inputs, no pulse)
# =========================
# Always have a dataframe to work with downstream
df, current_target = load_data()

st.subheader("Add a reading")
with st.form("bp_form", clear_on_submit=True):
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        sys_raw = st.text_input("Systolic (mmHg)", value="", placeholder="e.g., 120")
    with col2:
        dia_raw = st.text_input("Diastolic (mmHg)", value="", placeholder="e.g., 75")
    with col3:
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
        # Validate inputs
        sys_val, err1 = parse_int("Systolic", sys_raw, 50, 260)
        dia_val, err2 = parse_int("Diastolic", dia_raw, 30, 180)
        if err1: st.error(err1)
        if err2: st.error(err2)
        if not (err1 or err2):
            df, current_target = add_entry(sys_val, dia_val, notes, ts, "gsheets")
            st.success(f"Reading saved to {current_target}.")

import numpy as np

# =========================
# Table (fun version)
# =========================
st.subheader("Recent readings")
if df.empty:
    st.info("No data yet. Add your first reading above.")
else:
    show = df.sort_values("timestamp", ascending=False).copy()

    # Pretty timestamp: "Sun 8/10/25"  (month no leading zero; 2-digit year)
    show["When"] = show["timestamp"].apply(
        lambda x: f"{x.strftime('%a')} {x.month}/{x.day:02d}/{x.year%100:02d}"
    )

    # Compact BP and friendlier status
    status_emoji = {
        "Normal": "🟢",
        "Elevated": "🟡",
        "Hypertension Stage 1": "🟠",
        "Hypertension Stage 2": "🔴",
    }
    show["BP"] = show["systolic"].astype(int).astype(str) + "/" + show["diastolic"].astype(int).astype(str)
    show["Status"] = show["category"].map(lambda c: f"{status_emoji.get(c, '⚪')} {c}")
    show["Notes"] = show["notes"].fillna("")

    # Choose columns & hide the index
    show = show[["When", "BP", "Status", "Notes"]]
    st.dataframe(show.head(25), use_container_width=True, hide_index=True)

  
import matplotlib.dates as mdates

# ---------- Visualizations ----------
if not df.empty:
    st.subheader("Trends")

    df_plot = df.copy().sort_values("timestamp")
    df_plot["date"] = df_plot["timestamp"].dt.date

    # Rolling means
    df_plot.set_index("timestamp", inplace=True)
    for col in ["systolic", "diastolic"]:
        df_plot[f"{col}_7d_avg"] = df_plot[col].rolling("7D").mean()

    # ---- Line chart: systolic/diastolic and 7-day averages ----
    st.markdown("**Systolic & Diastolic over time** (with 7-day rolling average)")
    fig1, ax1 = plt.subplots()

    ax1.plot(df_plot.index, df_plot["systolic"], label="Systolic")
    ax1.plot(df_plot.index, df_plot["diastolic"], label="Diastolic")
    if df_plot["systolic_7d_avg"].notna().any() or df_plot["diastolic_7d_avg"].notna().any():
        ax1.plot(df_plot.index, df_plot["systolic_7d_avg"], linestyle="--", label="Systolic (7d avg)")
        ax1.plot(df_plot.index, df_plot["diastolic_7d_avg"], linestyle="--", label="Diastolic (7d avg)")

    ax1.set_xlabel("Date")
    ax1.set_ylabel("mmHg")
    ax1.legend()

    # Format the x-axis nicely
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig1.autofmt_xdate(rotation=45)

    st.pyplot(fig1)

    # ---- Scatter: systolic vs diastolic ----
    st.markdown("**Systolic vs Diastolic** (each point = a reading)")
    fig2, ax2 = plt.subplots()
    ax2.scatter(df["systolic"], df["diastolic"])

    ax2.set_xlabel("Systolic (mmHg)")
    ax2.set_ylabel("Diastolic (mmHg)")

    ax2.set_xlim(left=min(80, df["systolic"].min() - 5), right=max(180, df["systolic"].max() + 5))
    ax2.set_ylim(bottom=min(50, df["diastolic"].min() - 5), top=max(120, df["diastolic"].max() + 5))

    # Ensure scatter axis labels are clean
    ax2.xaxis.set_major_locator(plt.MaxNLocator(6))
    ax2.yaxis.set_major_locator(plt.MaxNLocator(6))

    st.pyplot(fig2)

   # ---- Weekly summary ----
st.subheader("Weekly summary")

if df.empty or "timestamp" not in df.columns:
    st.info("No data to summarize yet.")
else:
    df_week = df.copy()

    # Backfill derived columns if missing
    if {"systolic", "diastolic"}.issubset(df_week.columns):
        if "pulse_pressure" not in df_week.columns:
            df_week["pulse_pressure"] = df_week["systolic"] - df_week["diastolic"]
        if "map" not in df_week.columns:
            df_week["map"] = (df_week["diastolic"] + df_week["pulse_pressure"] / 3).round(1)

    # Week bucket (start of week)
    df_week["week"] = df_week["timestamp"].dt.to_period("W").apply(lambda p: p.start_time.date())

    # Only summarize columns that actually exist
    numeric_cols = [c for c in ["systolic", "diastolic", "map", "pulse_pressure"] if c in df_week.columns]
    if not numeric_cols:
        st.info("No numeric columns to summarize.")
    else:
        summary = df_week.groupby("week")[numeric_cols].agg(["count", "mean", "min", "max"])
        summary.columns = ["_".join(col).strip() for col in summary.columns.values]
        st.dataframe(summary, use_container_width=True)



# =========================
# Info
# =========================
with st.expander("How are categories defined?"):
    st.markdown("""
- **Normal:** Systolic < 120 and Diastolic < 80  
- **Elevated:** Systolic 120-129 and Diastolic < 80  
- **Hypertension Stage 1:** Systolic 130-139 or Diastolic 80-89  
- **Hypertension Stage 2:** Systolic >= 140 or Diastolic >= 90
""")
st.caption("Tip: Take two readings each time and log the average. Measure at consistent times daily, seated, with arm at heart level.")
