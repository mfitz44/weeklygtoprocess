import streamlit as st
import pandas as pd
from io import BytesIO
from fuzzywuzzy import process, fuzz

st.set_page_config(page_title="GTO Scorecard Generator", layout="wide")

st.title("Fairway Theory GTO Scorecard Generator")
st.markdown(
    "Upload your merged RG + DG raw data CSV, and get a clean GTO scorecard in seconds!"
)

@st.cache_data
ndef load_data(uploaded_file):
    return pd.read_csv(uploaded_file)


def compute_gto_metrics(df):
    # Step 1: Calculate Boom Score, weighted GTO Score, etc.
    # Example: boom_score already provided or calculate here
    # Step 2: Compute weighted GTO Score: .4*boom + .2*make_cut% + .2*top20% + .2*win%
    df['GTO_Score'] = (
        0.4 * df['Boom_Score'] +
        0.2 * df['MakeCut%'] +
        0.2 * df['Top20%'] +
        0.2 * df['Win%']
    )
    # Step 3: Convert raw RG ownership to preliminary GTO ownership
    df['Prelim_Ownership'] = df['GTO_Score'] / df['GTO_Score'].sum() * 600
    return df


def apply_filters_and_rescale(df):
    # Eliminate golfers with ceiling < 65
    df.loc[df['Ceiling'] < 65, 'Prelim_Ownership'] = 0
    # Eliminate bottom 20% of Prelim_Ownership before rescale
    threshold = df['Prelim_Ownership'].quantile(0.2)
    df.loc[df['Prelim_Ownership'] <= threshold, 'Prelim_Ownership'] = 0
    # Rescale to total exactly 600%
    total = df['Prelim_Ownership'].sum()
    if total > 0:
        df['GTO_Ownership_%'] = df['Prelim_Ownership'] / total * 600
    else:
        df['GTO_Ownership_%'] = 0
    # Set ownership <= 0.5% to zero
    df.loc[df['GTO_Ownership_%'] <= 0.5, 'GTO_Ownership_%'] = 0
    # Final rescale
    total2 = df['GTO_Ownership_%'].sum()
    if total2 > 0:
        df['GTO_Ownership_%'] = df['GTO_Ownership_%'] / total2 * 600
    return df


def generate_scorecard(df):
    # Select and order columns for final upload format
    cols = [
        'Name', 'Salary', 'Boom_Score', 'MakeCut%', 'Top20%', 'Win%',
        'GTO_Score', 'GTO_Ownership_%'
    ]
    scorecard = df[cols].copy()
    scorecard = scorecard.rename(
        columns={
            'Name': 'Golfer',
            'GTO_Ownership_%': 'GTO_Ownership'
        }
    )
    return scorecard


def to_csv_bytes(df):
    buffer = BytesIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue()

# --- Main UI ---
uploaded = st.file_uploader("Upload merged RG + DG CSV", type=['csv'])
if uploaded:
    raw = load_data(uploaded)
    st.success(f"Loaded {len(raw)} rows")
    # Process
    df_metrics = compute_gto_metrics(raw)
    df_filtered = apply_filters_and_rescale(df_metrics)
    scorecard = generate_scorecard(df_filtered)

    st.subheader("Preview GTO Scorecard")
    st.dataframe(scorecard)

    csv_bytes = to_csv_bytes(scorecard)
    st.download_button(
        label="Download GTO Scorecard",
        data=csv_bytes,
        file_name=f"gto_scorecard_{pd.Timestamp.today().strftime('%m%d%y')}.csv",
        mime='text/csv'
    )
else:
    st.info("Please upload a CSV file to begin.")
