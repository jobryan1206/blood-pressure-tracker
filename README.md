# Blood Pressure Logger (Streamlit)

A minimal, privacy-friendly blood pressure logger you can deploy to Streamlit Community Cloud (or run locally).

## Features
- Add systolic, diastolic, pulse, and notes
- Auto-timestamp (or set a custom date/time)
- Categorizes readings (Normal, Elevated, Stage 1/2)
- Visualizations: trends over time, rolling averages, and scatter plot
- Weekly summaries (count/mean/min/max)
- Download/restore CSV to back up your data

## Quick Start (Local)
1. Create and activate a virtual environment (optional).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   streamlit run app.py
   ```
4. Your data saves to `bp_data.csv` in the working directory.

## Deploy to Streamlit Community Cloud
1. Create a new public GitHub repo and upload these three files: `app.py`, `requirements.txt`, and (optionally) an empty `bp_data.csv`.
2. Go to Streamlit Community Cloud and create a new app pointed at your repo.
3. Click "Deploy." Your app will be live and ready to use.

### Notes
- Streamlit Cloud file writes are ephemeral on redeploy; use the sidebar **Download CSV** to back up regularly, and **Restore** to merge a CSV if needed.
- If you want always-on storage, we can wire this to Google Sheets or a tiny SQLite database with a hosted file (e.g., on Supabase). Ask me and I'll add it.