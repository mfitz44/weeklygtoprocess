import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="Fairway Theory GTO Scorecard Generator", layout="wide")

@st.cache_data
 def load_data(uploaded_file):
    return pd.read_csv(uploaded_file)

 def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()

 def main():
    st.title("Fairway Theory GTO Scorecard Generator")
    st.markdown(
        "Upload your merged RG + DG raw data CSV to generate GTO scorecards in line with SOP steps 3–7."
    )
    uploaded = st.file_uploader("Upload merged RG + DG CSV", type=["csv"])
    if not uploaded:
        st.info("Please upload a merged RG + DG raw data CSV to begin.")
        return

    df = load_data(uploaded)
    st.success(f"Loaded {len(df)} rows")
    today = pd.Timestamp.today().strftime("%m%d%y")

    # Step 3: Salary-Driven Base Ownership Calculation
    s_min, s_max = df['Salary'].min(), df['Salary'].max()
    df['NormSal'] = (df['Salary'] - s_min) / (s_max - s_min)
    df['RawBaseOwn%'] = 0.5 + 19.5 * df['NormSal']
    st.download_button(
        label="Download Step 3: Salary Ownership",
        data=to_csv_bytes(df[['Golfer', 'RawBaseOwn%']]),
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
        data=to_csv_bytes(df[['Golfer', 'DG_Composite', 'RawDGOwn%']]),
        file_name=f"GTO_DGOwn_{today}.csv",
        mime='text/csv'
    )

    # Step 5: Pre-Elimination Combined Ownership
    df['PreElimOwn%'] = 0.5 * (df['RawBaseOwn%'] + df['RawDGOwn%'])
    st.download_button(
        label="Download Step 5: Pre-Elim Ownership",
        data=to_csv_bytes(df[['Golfer', 'PreElimOwn%']]),
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
        data=to_csv_bytes(df[['Golfer', 'FinalOwn%']]),
        file_name=f"GTO_FinalOwn_{today}.csv",
        mime='text/csv'
    )

    # Step 7: Final File Preparation for Builder
    df_scorecard = df[df['FinalOwn%'] > 0].copy()
    df_scorecard = df_scorecard.rename(
        columns={
            'Golfer': 'Name',
            'FinalOwn%': 'GTO_Ownership%'
        }
    )
    # Include original RG ownership as Projected_Ownership%
    df_scorecard['Projected_Ownership%'] = df.set_index('Golfer').loc[
        df_scorecard['Name'], 'RG_Ownership%'
    ].values
    # Select & reorder columns per SOP
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
