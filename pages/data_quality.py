"""Data Quality & Information."""
import pandas as pd
import streamlit as st

from analytics import system as sy
from components import data
from components.layout import page_header, section
from components.tables import data_table
from config import settings
from config.kpi_definitions import KPI_DEFINITIONS

page_header("Data Quality & Information", "What data is loaded, how it was validated and transformed, and how every KPI is defined.")
st.warning(settings.DATA_PERIOD_NOTICE + " The dataset has no cost data (revenue is not profit) and no inventory data.")

section("Database")
status = data.q(sy.get_database_status, None)
period = data.q(sy.get_data_period, None)
c1, c2, c3 = st.columns(3)
c1.metric("Orders loaded", f"{period['orders']:,}", border=True)
c2.metric("First purchase", str(period["first_day"]), border=True)
c3.metric("Last purchase", str(period["last_day"]), border=True)
with st.expander("Connection details"):
    st.json({k: v for k, v in status.items() if "password" not in k.lower()})
data_table(data.q(sy.table_row_counts, None), "table_row_counts", "dq_counts")

section("Latest pipeline run")
proc = data.q(sy.get_data_processing_status, None)
if proc["run"] is None:
    st.info("No pipeline run is recorded in this database.")
else:
    run = proc["run"]
    st.write(f"Run **{run['run_id']}** · status **{run['status']}** · started {run['started_at']} · source `{run['raw_dir']}`")
    t1, t2 = st.tabs(["Rows loaded", "Transformations applied"])
    with t1:
        data_table(proc["loads"], "rows_loaded", "dq_loads")
    with t2:
        st.caption("Every cleaning step, with row counts before and after.")
        data_table(proc["transformations"], "transformation_log", "dq_trans")

section("Validation report")
rep = data.q(sy.load_quality_report, None)
if not rep:
    st.info("No data-quality report is stored. Run the pipeline to create one.")
else:
    checks = rep.get("checks", [])
    if checks:
        df = pd.DataFrame(checks)
        counts = df["status"].value_counts().to_dict() if "status" in df else {}
        st.write("  ·  ".join(f"{k}: **{v}**" for k, v in counts.items()))
        data_table(df, "quality_checks", "dq_checks")
    else:
        st.json(rep, expanded=False)

section("Column profile")
from ingestion.schema_spec import WAREHOUSE_LOAD_ORDER  # noqa: E402

table = st.selectbox("Table", list(WAREHOUSE_LOAD_ORDER), key="dq_table")
data_table(data.q(sy.describe_columns, None, table), f"columns_{table}", "dq_cols")

section("KPI definitions", "Every KPI card in the app uses one of these definitions as its tooltip.")
defs = pd.DataFrame([{"KPI": d.label, "Formula": d.formula, "Denominator": d.denominator, "Null handling": d.null_handling}
                     for d in KPI_DEFINITIONS.values()])
data_table(defs, "kpi_definitions", "dq_kpis")
