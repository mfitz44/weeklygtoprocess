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
    clean = re.sub(r"[^a-zA-Z\s]", "", str(name)).lower().strip()
    tokens = clean.split()
    tokens.sort()
    return " ".join(tokens)


def find_name_column(df: pd.DataFrame) -> str:
    candidates = [col for col in df.columns if col.lower() in ['name', 'golfer', 'player', 'player name']]
    return candidates[0] if candidates else df.columns[0]


def detect_and_rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        col_lc = col.lower()
        # RG fields
        if col_lc == 'salary':
            rename_map[col] = 'Salary'
        elif 'ceil' in col_lc:
            rename_map[col] = 'Ceiling'
        elif re.search(r'\b(fpts|proj[_ ]?pt)s?\b', col_lc):
            rename_map[col] = 'RG_ProjPts'
        elif re.search(r'\b(proj[_ ]?own|ownership)\b', col_lc):
            rename_map[col] = 'RG_Ownership%'
        # DG fields
        elif col_lc in ['win', 'win%']:
            rename_map[col] = 'DG_Win%'
        elif 'top' in col_lc and '20' in col_lc:
            rename_map[col] = 'DG_Top20%'
        elif 'top' in col_lc and '10' in col_lc:
            rename_map[col] = 'DG_Top10%'
        elif 'top' in col_lc and '5' in col_lc:
            rename_map[col] = 'DG_Top5%'
        elif 'make' in col_lc and 'cut' in col_lc:
            rename_map[col] = 'DG_MakeCut%'
    return df.rename(columns=rename_map)


def main():
    st.title("Fairway Theory GTO Scorecard Generator")
    st.markdown(
        "Upload your Rotogrinders and DataGolf CSVs separately (or a merged raw file) to generate a builder-ready GTO scorecard per SOP Steps 1–7."
    )

    # Step 1: Upload raw data files
    rg_file = st.file_uploader("Upload Rotogrinders CSV (RG)", type=["csv"], key="rg")
    dg_file = st.file_uploader("Upload DataGolf CSV (DG)", type=["csv"], key="dg")

    if not rg_file and not dg_file:
        st.info("Please upload at least one CSV. For a merged raw file, upload it as RG.")
        return

    # Load data
    rg_df = load_data(rg_file) if rg_file else None
    dg_df = load_data(dg_file) if dg_file else None

    # If only merged raw provided, set both to same
    if rg_df is not None and dg_df is None:
        dg_df = rg_df.copy()
    # If only DG provided
    if dg_df is not None and rg_df is None:
        rg_df = dg_df.copy()

    # Detect name cols and unify
    rg_name_col = find_name_column(rg_df)
    dg_name_col = find_name_column(dg_df)
    rg_df = rg_df.rename(columns={rg_name_col: 'Name'})
    dg_df = dg_df.rename(columns={dg_name_col: 'Name'})

    # Step 2: Fuzzy merge on normalized names
    rg_df['Name_norm'] = rg_df['Name'].apply(normalize_name)
    dg_df['Name_norm'] = dg_df['Name'].apply(normalize_name)
    dg_norms = dg_df['Name_norm'].tolist()
    mapping = {orig: difflib.get_close_matches(norm, dg_norms, n=1, cutoff=0.8)[0]
               if difflib.get_close_matches(norm, dg_norms, n=1, cutoff=0.8) else None
               for orig, norm in zip(rg_df['Name'], rg_df['Name_norm'])}
    rg_df['Matched_DG_Norm'] = rg_df['Name'].map(mapping)
    merged = pd.merge(rg_df, dg_df, left_on='Matched_DG_Norm', right_on='Name_norm', suffixes=("", "_dg"))
    merged = merged.drop(columns=['Matched_DG_Norm', 'Name_norm', 'Name_norm_dg'], errors='ignore')

    st.success(f"Merged raw data: {len(merged)} rows")
    today = pd.Timestamp.today().strftime("%m%d%y")
    st.download_button(
        label="Download Step 2: Merged Raw Data",
        data=to_csv_bytes(merged),
        file_name=f"GTO_Raw_{today}.csv",
        mime='text/csv'
    )

    df = detect_and_rename_columns(merged)

    # Verify required RG columns
    for col in ['Salary', 'Ceiling', 'RG_ProjPts', 'RG_Ownership%']:
        if col not in df.columns:
            st.error(f"Required column '{col}' missing after renaming."
                     f" Found: {df.columns.tolist()}")
            return

    # Verify required DG cols
    for col in ['DG_Win%', 'DG_Top20%', 'DG_Top10%', 'DG_Top5%', 'DG_MakeCut%']:
        if col not in df.columns:
            st.error(f"Required DG column '{col}' missing after renaming."
                     f" Found: {df.columns.tolist()}")
            return

    # Step 3: Salary-Driven Base Ownership
    s_min, s_max = df['Salary'].min(), df['Salary'].max()
    df['RawBaseOwn%'] = 0.5 + 19.5 * ((df['Salary'] - s_min) / (s_max - s_min))
    st.download_button("Download Step 3: Salary Ownership",
                       data=to_csv_bytes(df[['Name', 'RawBaseOwn%']]),
                       file_name=f"GTO_SalaryOwn_{today}.csv",
                       mime='text/csv')

    # Step 4: DG Composite
    dg_fields = ['DG_MakeCut%', 'DG_Top20%', 'DG_Top10%', 'DG_Top5%', 'DG_Win%']
    df['DG_Composite'] = df[dg_fields].mean(axis=1)
    dg_min, dg_max = df['DG_Composite'].min(), df['DG_Composite'].max()
    df['RawDGOwn%'] = 0.5 + 19.5 * ((df['DG_Composite'] - dg_min) / (dg_max - dg_min))
    st.download_button("Download Step 4: DG Ownership",
                       data=to_csv_bytes(df[['Name', 'DG_Composite', 'RawDGOwn%']]),
                       file_name=f"GTO_DGOwn_{today}.csv",
                       mime='text/csv')

    # Step 5: Pre-Elimination
    df['PreElimOwn%'] = 0.5 * (df['RawBaseOwn%'] + df['RawDGOwn%'])
    st.download_button("Download Step 5: Pre-Elim Ownership",
                       data=to_csv_bytes(df[['Name', 'PreElimOwn%']]),
                       file_name=f"GTO_PreElim_{today}.csv",
                       mime='text/csv')

    # Step 6: Elimination & Rescaling
    df['FinalOwn%'] = 0.0
    threshold = df['PreElimOwn%'].quantile(0.2)
    survivors = df['PreElimOwn%'] > threshold
    p_min, p_max = df.loc[survivors, 'PreElimOwn%'].min(), df.loc[survivors, 'PreElimOwn%'].max()
    norm_pre = (df.loc[survivors, 'PreElimOwn%'] - p_min) / (p_max - p_min)
    mapped = 0.7 + 21.5 * norm_pre
    df.loc[survivors, 'FinalOwn%'] = mapped * (600.0 / mapped.sum())
    st.download_button("Download Step 6: Final Ownership",
                       data=to_csv_bytes(df[['Name', 'FinalOwn%']]),
                       file_name=f"GTO_FinalOwn_{today}.csv",
                       mime='text/csv')

    # Step 7: Prep Final Scorecard
    df_score = df[df['FinalOwn%'] > 0].copy()
    df_score = df_score.rename(columns={'FinalOwn%': 'GTO_Ownership%'})
    df_score['Projected_Ownership%'] = df.set_index('Name')['RG_Ownership%'].loc[df_score['Name']].values
    final_cols = ['Name', 'Salary', 'Ceiling', 'RG_ProjPts', 'DG_Composite',
                  'Projected_Ownership%', 'GTO_Ownership%']
    df_score = df_score[final_cols]

    st.subheader("Final GTO Scorecard")
    st.dataframe(df_score)
    st.download_button("Download GTO Scorecard",
                       data=to_csv_bytes(df_score),
                       file_name=f"gto_scorecard_{today}.csv",
                       mime='text/csv')

if __name__ == '__main__':
    main()
