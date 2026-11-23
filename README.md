# MIAA / NFHS Dual Meet Swim Scorer

A local Python + Streamlit web application for timing, validating, and scoring Massachusetts high school (MIAA / NFHS) dual swim meets.

## Quickstart

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Mac / Linux:
   source .venv/bin/activate
   # Windows:
   .venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the automated NFHS rules test suite:
   ```bash
   PYTHONPATH=. pytest -v
   ```

4. Launch the web app:
   ```bash
   streamlit run app.py
   ```

## Sample Rosters
Upload `sample_rosters/home_team_roster.csv` and `sample_rosters/visiting_team_roster.csv` via the **Import Team Rosters (CSV)** expander in the sidebar to test the swimmer dropdowns.
