"""Business Reports: PDF, Excel and CSV exports of the same report."""
import streamlit as st

from components import data
from components.filters import current
from components.layout import page_header, section
from reports.csv_exporter import dataframes_to_zip_bytes
from reports.excel_generator import dataframes_to_excel_bytes
from reports.pdf_generator import report_to_pdf_bytes
from reports.report_builder import build_business_report

f = current()
page_header("Business Reports", "A downloadable summary for the current filters. PDF, Excel and CSV are built from the same data, so they always agree.")


@st.cache_data(ttl=3600, show_spinner="Building report…", max_entries=8)
def _build(filters, with_opps: bool):
    rep = build_business_report(data.engine(), filters, include_opportunities=with_opps)
    return rep, report_to_pdf_bytes(rep), dataframes_to_excel_bytes(rep.all_frames()), dataframes_to_zip_bytes(rep.all_frames())


with_opps = st.toggle("Include the opportunity table", value=True, key="rep_opps",
                      help="Adds the top 25 findings of the Business Opportunity Finder (slower on large data).")
if st.button("Build report", type="primary", key="rep_build"):
    st.session_state["report_key"] = (f, with_opps)

key = st.session_state.get("report_key")
if key != (f, with_opps):
    st.info("Choose the filters and options, then press **Build report**. The report reflects the filters in the sidebar when you build it.")
    st.stop()

rep, pdf, xlsx, zipped = _build(f, with_opps)
st.success(f"Report built {rep.generated_at:%Y-%m-%d %H:%M} · filters: {rep.filters_text}")
stem = "marketpulse_report"
c1, c2, c3 = st.columns(3)
c1.download_button("Download PDF", pdf, f"{stem}.pdf", "application/pdf", width="stretch", key="dl_pdf")
c2.download_button("Download Excel", xlsx, f"{stem}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch", key="dl_xlsx")
c3.download_button("Download CSV (zip)", zipped, f"{stem}_csv.zip", "application/zip", width="stretch", key="dl_zip")

section("Preview")
st.dataframe(rep.kpis[["KPI", "Value"]], hide_index=True, width="stretch")
for name, df in rep.tables.items():
    with st.expander(name):
        st.dataframe(df, hide_index=True, width="stretch")
for sec, items in rep.findings.items():
    with st.expander(f"Findings: {sec}"):
        for i in items:
            st.markdown(f"**{i.title}**  \n{i.detail}  \n*Rule: {i.rule}*")
with st.expander("Limitations stated in the report"):
    for x in rep.limitations:
        st.markdown(f"- {x}")
