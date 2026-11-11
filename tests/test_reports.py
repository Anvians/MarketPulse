"""Report builder and exporters (PDF / Excel / CSV zip) on the synthetic fixture."""
from __future__ import annotations

import zipfile
from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import load_workbook

from analytics.base import Filters
from reports.csv_exporter import dataframes_to_zip_bytes
from reports.excel_generator import dataframes_to_excel_bytes
from reports.pdf_generator import report_to_pdf_bytes
from reports.report_builder import LIMITATIONS, build_business_report

NOW = datetime(2026, 1, 2, 3, 4)


@pytest.fixture()
def report(warehouse):
    return build_business_report(warehouse, None, now=NOW)


def test_report_kpis_match_the_hand_checked_fixture(report):
    k = dict(zip(report.kpis["KPI"], report.kpis["Value"]))
    assert k["Total revenue"] == "R$ 450.00" and k["Total orders"] == "4"
    assert k["Average order value"] == "R$ 112.50"
    assert "Denominator" in report.kpis["Definition"].iloc[0]


def test_report_follows_filters(warehouse):
    r = build_business_report(warehouse, Filters(states=("SP",)), now=NOW)
    assert dict(zip(r.kpis["KPI"], r.kpis["Value"]))["Total revenue"] == "R$ 220.00"
    assert "SP" in r.filters_text


def test_report_states_the_dataset_limits(report):
    text = " ".join(report.limitations)
    assert "2016-2018" in text and "not profit" in text and "inventory" in text
    assert report.limitations == LIMITATIONS


def test_pdf_is_a_valid_multi_section_document(report):
    pdf = report_to_pdf_bytes(report)
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 3000


def test_pdf_builds_for_a_filter_with_no_rows(warehouse):
    r = build_business_report(warehouse, Filters(order_statuses=("canceled",)), now=NOW)
    assert report_to_pdf_bytes(r).startswith(b"%PDF")


def test_excel_has_one_sheet_per_table_and_an_about_sheet(report):
    wb = load_workbook(BytesIO(dataframes_to_excel_bytes(report.all_frames())))
    assert {"About", "KPIs", "Monthly revenue", "Top categories"} <= set(wb.sheetnames)
    about = [r[1].value for r in wb["About"].iter_rows(min_row=2)]
    assert any("not profit" in str(v) for v in about)


def test_csv_zip_contains_every_table(report):
    z = zipfile.ZipFile(BytesIO(dataframes_to_zip_bytes(report.all_frames())))
    assert {"About.csv", "KPIs.csv", "Monthly_revenue.csv"} <= set(z.namelist())
    assert z.read("KPIs.csv").startswith(b"\xef\xbb\xbf")             # UTF-8 BOM for Excel


def test_findings_sheet_lists_rules(report):
    frames = report.all_frames()
    assert "Findings" in frames and frames["Findings"]["Rule"].str.len().gt(5).all()
