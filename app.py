import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="Blood Pressure Logger", page_icon="🩺", layout="wide")

st.title("🩺 Blood Pressure Logger")
st.caption("Log blood pressure readings, add notes, and visualize trends over time.")

# ---------- Utility ----------

CSV_PATH = "bp_data.csv"

BP_CATEGORIES = [
    ("Normal", (0, 120), (0, 80)),
    ("Elevated", (120, 130), (0, 80)),
    ("Hypertension Stage 1", (130, 140), (80, 90)),
    ("Hypertension Stage 2", (140, 10_000), (90, 10_000)),
]

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

def load_data():
    try:
        df = pd.read_csv(CSV_PATH, parse_dates=["timestamp"])
        # clean types if needed
        for col in ["systolic", "diastolic", "pulse"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["timestamp"])
    except FileNotFoundError:
        cols = ["timestamp", "systolic", "diastolic", "pulse", "notes", "category", "map", "pulse_pressure"]
        return pd.DataFrame(columns=cols)

def save_data(df):
    df.to_csv(CSV_PATH, index=False)

def add_entry(sys, dia, pulse, notes, ts):
    df = load_data()
    category = categorize_bp(sys, dia)
    pulse_pressure = sys - dia
    mean_arterial_pressure = round(dia + (pulse_pressure/3), 1)
    row = {
        "timestamp": pd.to_datetime(ts),
        "systolic": int(sys),
        "diastolic": int(dia),
        "pulse": int(pulse) if pulse is not None else None,
        "notes": notes or "",
        "category": category,
        "map": mean_arterial_pressure,
        "pulse_pressure": pulse_pressure,
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df = df.sort_values("timestamp")
    save_data(df)
    return df

def df_download_bytes(df):
    out = BytesIO()
    df.to_csv(out, index=False)
    out.seek(0)
    return out

# ---------- Sidebar: Data ops ----------
with st.sidebar:
    st.header("Data")
    st.write("• Data is saved to `bp_data.csv` in the app's working directory.")
    st.write("• Use the controls below to back up or restore your data.")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("⬇️ Download CSV"):
            df = load_data()
            st.download_button("Save file", data=df_download_bytes(df), file_name="bp_data.csv", mime="text/csv")
    with col_b:
        uploaded = st.file_uploader("Restore/merge from CSV", type=["csv"], label_visibility="collapsed")
        if uploaded is not None:
            try:
                existing = load_data()
                incoming = pd.read_csv(uploaded, parse_dates=["timestamp"])
                combined = pd.concat([existing, incoming], ignore_index=True).drop_duplicates().sort_values("timestamp")
                save_data(combined)
                st.success(f"Imported {len(incoming)} rows. Total rows: {len(combined)}.")
            except Exception as e:
                st.error(f"Import failed: {e}")

    if st.button("🗑️ Clear ALL data"):
        save_data(load_data().iloc[:0])
        st.warning("All data cleared. (CSV overwritten)")

st.divider()

# ---------- Input form ----------
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

    # Optional manual timestamp
    manual_ts = st.checkbox("Set custom date & time")
    if manual_ts:
        col_dt1, col_dt2 = st.columns(2)
        with col_dt1:
            date = st.date_input("Date", value=datetime.now().date())
        with col_dt2:
            time = st.time_input("Time", value=datetime.now().time().replace(microsecond=0))
        ts = datetime.combine(date, time)
    else:
        ts = datetime.now()

    submitted = st.form_submit_button("Add reading", type="primary")
    if submitted:
        df = add_entry(systolic, diastolic, pulse, notes, ts)
        st.success("Reading saved.")
    else:
        df = load_data()

# ---------- Data table ----------
st.subheader("Recent readings")
if df.empty:
    st.info("No data yet. Add your first reading above.")
else:
    # Show most recent first
    df_view = df.sort_values("timestamp", ascending=False).copy()
    # nice formatting
    df_view["timestamp"] = df_view["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(df_view.head(25), use_container_width=True)

# ---------- Visualizations ----------
if not df.empty:
    st.subheader("Trends")

    df_plot = df.copy().sort_values("timestamp")
    df_plot["date"] = df_plot["timestamp"].dt.date

    # Rolling means
    df_plot.set_index("timestamp", inplace=True)
    for col in ["systolic", "diastolic"]:
        df_plot[f"{col}_7d_avg"] = df_plot[col].rolling("7D").mean()

    # Line chart: systolic/diastolic and 7-day averages
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
    st.pyplot(fig1)

    # Scatter: systolic vs diastolic with categories
    st.markdown("**Systolic vs Diastolic** (each point = a reading)")
    fig2, ax2 = plt.subplots()
    ax2.scatter(df["systolic"], df["diastolic"])
    ax2.set_xlabel("Systolic (mmHg)")
    ax2.set_ylabel("Diastolic (mmHg)")
    ax2.set_xlim(left=min(80, df["systolic"].min() - 5), right=max(180, df["systolic"].max() + 5))
    ax2.set_ylim(bottom=min(50, df["diastolic"].min() - 5), top=max(120, df["diastolic"].max() + 5))
    st.pyplot(fig2)

    # Weekly summary
    st.subheader("Weekly summary")
    df_week = df.copy()
    df_week["week"] = df_week["timestamp"].dt.to_period("W").apply(lambda p: p.start_time.date())
    summary = (
        df_week.groupby("week")[["systolic", "diastolic", "pulse", "map", "pulse_pressure"]]
        .agg(["count", "mean", "min", "max"])
    )
    # Flatten columns
    summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
    st.dataframe(summary, use_container_width=True)

# ---------- Info ----------
with st.expander("How are categories defined?"):
    st.markdown(
        """
- **Normal:** Systolic < 120 and Diastolic < 80  
- **Elevated:** Systolic 120-129 and Diastolic < 80  
- **Hypertension Stage 1:** Systolic 130-139 or Diastolic 80-89  
- **Hypertension Stage 2:** Systolic >= 140 or Diastolic >= 90
        """
    )

st.caption("Tip: Take two readings each time and log the average. Try to measure at the same times daily, seated, feet on floor, and arm supported at heart level.")