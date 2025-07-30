import streamlit as st
import pandas as pd
from io import BytesIO
import difflib
import re

st.set_page_config(page_title="Fairway Theory GTO Scorecard Generator", layout="wide")

@st.cache_data
def load_data(uploaded_file):
    return pd.read_csv(uploaded_file)

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()

def normalize_name(name: str) -> str:
    # Lowercase, remove punctuation, split tokens, sort, and rejoin for consistent matching
    clean = re.sub(r"[^a-zA-Z\s]", "", name).lower().strip()
    tokens = clean.split()
    tokens.sort()
    return " ".join(tokens)

def main():
    st.title("Fairway Theory GTO Scorecard Generator")
    st.markdown(
        "Upload your Rotogrinders and DataGolf CSVs separately to generate a builder-ready GTO scorecard per SOP Steps 1–7."
    )

    # Step 1: Upload raw data files
    rg_file = st.file_uploader("Upload Rotogrinders CSV (RG)", type=["csv"], key="rg")
    dg_file = st.file_uploader("Upload DataGolf CSV (DG)", type=["csv"], key="dg")

    if not rg_file or not dg_file:
        st.info("Please upload both Rotogrinders and DataGolf CSVs to begin.")
        return

    # Load data
    rg_df = load_data(rg_file)
    dg_df = load_data(dg_file)

    # Normalize column names
    if 'Golfer' in rg_df.columns:
        rg_df = rg_df.rename(columns={'Golfer': 'Name'})
    if 'Golfer' in dg_df.columns:
        dg_df = dg_df.rename(columns={'Golfer': 'Name'})

    # Create normalized name keys for fuzzy matching
    rg_df['Name_norm'] = rg_df['Name'].apply(normalize_name)
    dg_df['Name_norm'] = dg_df['Name'].apply(normalize_name)

    # Step 2: Fuzzy merge RG & DG using normalized tokens
    dg_norms = dg_df['Name_norm'].tolist()
    mapping = {}
    for orig, norm in zip(rg_df['Name'], rg_df['Name_norm']):
        match_norm = difflib.get_close_matches(norm, dg_norms, n=1, cutoff=0.8)
        mapping[orig] = match_norm[0] if match_norm else None
    rg_df['Matched_DG_Norm'] = rg_df['Name'].map(mapping)
    merged = pd.merge(rg_df, dg_df, left_on='Matched_DG_Norm', right_on='Name_norm', suffixes=("", "_dg"))
    # Drop helper columns
    merged = merged.drop(columns=['Matched_DG_Norm', 'Name_dg', 'Name_norm', 'Name_norm_dg'], errors='ignore')

    st.success(f"Merged raw data: {len(merged)} rows")
    today = pd.Timestamp.today().strftime("%m%d%y")
    st.download_button(
        label="Download Step 2: Merged Raw Data",
        data=to_csv_bytes(merged),
        file_name=f"GTO_Raw_{today}.csv",
        mime='text/csv'
    )

    df = merged

    # Step 3: Salary-Driven Base Ownership Calculation
    s_min, s_max = df['Salary'].min(), df['Salary'].max()
    df['NormSal'] = (df['Salary'] - s_min) / (s_max - s_min)
    df['RawBaseOwn%'] = 0.5 + 19.5 * df['NormSal']
    st.download_button(
        label="Download Step 3: Salary Ownership",
        data=to_csv_bytes(df[['Name', 'RawBaseOwn%']]),
        file_name=f"GTO_SalaryOwn_{today}.csv",
        mime='text/csv'
    )

    # Step 4: DataGolf Composite Odds Ownership Calculation
    dg_fields = ['DG_MakeCut%', 'DG_Top20%', 'DG_Top10%', 'DG_Top5%', 'DG_Win%']
    df['DG_Composite'] = df[dg_fields].mean(axis=1)
    dg_min, dg_max = df['DG_Composite'].min(), df['DG_Composite'].max()
    df['RawDGOwn%'] = 0.5 + 19.5 * ((df['DG_Composite'] - dg_min) / (dg_max - dg_min))
    st.download_button(
        label="Download Step 4: DG Ownership",
        data=to_csv_bytes(df[['Name', 'DG_Composite', 'RawDGOwn%']]),
        file_name=f"GTO_DGOwn_{today}.csv",
        mime='text/csv'
    )

    # Step 5: Pre-Elimination Combined Ownership
    df['PreElimOwn%'] = 0.5 * (df['RawBaseOwn%'] + df['RawDGOwn%'])
    st.download_button(
        label="Download Step 5: Pre-Elim Ownership",
        data=to_csv_bytes(df[['Name', 'PreElimOwn%']]),
        file_name=f"GTO_PreElim_{today}.csv",
        mime='text/csv'
    )

    # Step 6: Elimination & Rescaling
    df['FinalOwn%'] = 0.0
    threshold = df['PreElimOwn%'].quantile(0.2)
    survivors = df['PreElimOwn%'] > threshold
    p_min, p_max = df.loc[survivors, 'PreElimOwn%'].min(), df.loc[survivors, 'PreElimOwn%'].max()
    norm_pre = (df.loc[survivors, 'PreElimOwn%'] - p_min) / (p_max - p_min)
    mapped = 0.7 + 21.5 * norm_pre
    factor = 600.0 / mapped.sum()
    df.loc[survivors, 'FinalOwn%'] = mapped * factor
    st.download_button(
        label="Download Step 6: Final Ownership",
        data=to_csv_bytes(df[['Name', 'FinalOwn%']]),
        file_name=f"GTO_FinalOwn_{today}.csv",
        mime='text/csv'
    )

    # Step 7: Final File Preparation for Builder
    df_scorecard = df[df['FinalOwn%'] > 0].copy()
    df_scorecard = df_scorecard.rename(columns={'FinalOwn%': 'GTO_Ownership%'})
    df_scorecard['Projected_Ownership%'] = df.set_index('Name').loc[df_scorecard['Name'], 'RG_Ownership%'].values
    final_cols = [
        'Name', 'Salary', 'Ceiling', 'RG_ProjPts', 'DG_Composite',
        'Projected_Ownership%', 'GTO_Ownership%'
    ]
    df_scorecard = df_scorecard[final_cols]

    st.subheader("Final GTO Scorecard")
    st.dataframe(df_scorecard)
    st.download_button(
        label="Download GTO Scorecard",
        data=to_csv_bytes(df_scorecard),
        file_name=f"gto_scorecard_{today}.csv",
        mime='text/csv'
    )

if __name__ == '__main__':
    main()
