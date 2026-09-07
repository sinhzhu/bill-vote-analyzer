import tempfile
import os

import streamlit as st

from congress_analyzer import Congress, HouseChamber, SenateChamber


st.set_page_config(page_title="Bill & Vote Analyzer", layout="centered")
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap');
    html, body, [class*="st-"], .stMarkdown, .stText {
        font-family: "Instrument Serif", Georgia, "Times New Roman", serif !important;
    }
    .stApp { background: #071600; color: #e4ede1; }
    [data-testid="stSidebar"] { background: #16240f; }
    a { color: #c1bcbc !important; }
    a:hover { color: #5b5b5b !important; }
    .stTable td, .stTable th { color: #e4ede1; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Legislative Bill & Vote Analyzer")
st.write("Analyze congress.gov roll-call CSVs (e.g. House votes 362 and 295). "
         "The app counts Yea/Nay, checks pass/fail, and scores party-line, "
         "bipartisanship, and agreement.")

uploads = st.file_uploader("Upload 1-2 vote CSVs", type="csv",
                           accept_multiple_files=True)

bill_ids = st.text_input("Bill labels (comma-separated, optional)",
                         value="h119-362, h119-295")

if uploads:
    labels = [b.strip() or f"bill-{i+1}"
              for i, b in enumerate(bill_ids.split(","))]
    while len(labels) < len(uploads):
        labels.append(f"bill-{len(labels)+1}")

    cong = Congress()
    for up, bid in zip(uploads, labels):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(up.getvalue())
            tmp_path = tmp.name
        try:
            cong.load_congress_gov_csv(tmp_path, bid, bid, "house")
        finally:
            os.unlink(tmp_path)

    st.subheader(f"Loaded: {len(cong.legislators)} lawmakers, "
                 f"{len(cong.bills)} bills")
    st.write(f"House quorum = {HouseChamber().quorum()} | "
             f"Senate quorum = {SenateChamber().quorum()}")

    for bid, bill in cong.bills.items():
        t = bill.tally()
        from congress_analyzer import VoteChoice
        st.markdown(f"### {bid} — {'PASSED' if bill.passed() else 'FAILED'}")
        st.write(f"Yea={t[VoteChoice.YEA]} Nay={t[VoteChoice.NAY]} "
                 f"Abstain={t[VoteChoice.ABSTAIN]} Absent={t[VoteChoice.ABSENT]} | "
                 f"party-line={bill.party_line_score(cong.legislators):.2f}")

    st.subheader("Most bipartisan (cross party lines most)")
    rows = []
    for lid, score in cong.most_bipartisan(10):
        leg = cong.legislators[lid]
        rows.append({"Name": leg.name, "Party": leg.party,
                     "State": leg.state, "Score": round(score, 2)})
    st.table(rows)

    st.subheader("Agreement rate between two lawmakers")
    names = sorted(cong.legislators.keys())
    c1, c2 = st.columns(2)
    with c1:
        id1 = st.selectbox("Person 1", names, index=0)
    with c2:
        id2 = st.selectbox("Person 2", names,
                           index=min(1, len(names) - 1))
    st.write(f"Agreement: **{cong.agreement_rate(id1, id2):.0%}**")
else:
    st.info("Upload a CSV(s) to begin. Or try the sample files in the github repo (in demo-data)!")
