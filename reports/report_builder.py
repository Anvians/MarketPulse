"""Assemble the business report as data (metadata, KPI table, tables, findings).

The same ``Report`` feeds the PDF, Excel and CSV exports, so all three always
agree. Every number comes from the analytics layer; nothing is typed in here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from sqlalchemy.engine import Engine

from analytics import executive, growth, logistics, opportunities, revenue
from analytics.base import Filters, Insight
from analytics.system import get_data_period
from components.formatting import money, number, pct, score
from config import settings
from config.kpi_definitions import KPI_DEFINITIONS

LIMITATIONS = (
    settings.DATA_PERIOD_NOTICE,
    "Revenue is product revenue (sum of item prices on non-canceled orders); freight is reported separately. "
    "The dataset has no costs, so revenue is not profit.",
    "The dataset has no inventory data, so nothing here speaks to stock levels.",
    "Findings are rule-based prompts for investigation, not forecasts or proof of cause.",
)


@dataclass
class Report:
    title: str
    generated_at: datetime
    filters_text: str
    period_text: str
    kpis: pd.DataFrame                       # KPI, Value, Definition
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    findings: dict[str, list[Insight]] = field(default_factory=dict)
    limitations: tuple[str, ...] = LIMITATIONS

    def all_frames(self) -> dict[str, pd.DataFrame]:
        """Every table (KPIs and an 'About' sheet included) for Excel / CSV export."""
        about = pd.DataFrame({"Item": ["Report", "Generated", "Data period", "Filters", *[f"Limitation {i + 1}" for i in range(len(self.limitations))]],
                              "Value": [self.title, self.generated_at.strftime("%Y-%m-%d %H:%M"), self.period_text, self.filters_text, *self.limitations]})
        frames = {"About": about, "KPIs": self.kpis, **self.tables}
        rows = [{"Section": sec, "Finding": i.title, "Detail": i.detail, "Rule": i.rule, "Severity": i.severity}
                for sec, items in self.findings.items() for i in items]
        if rows:
            frames["Findings"] = pd.DataFrame(rows)
        return frames


def _kpi_rows(k: dict) -> list[tuple[str, str]]:
    return [
        ("total_revenue", money(k["total_revenue"])), ("total_orders", number(k["total_orders"])),
        ("total_customers", number(k["total_customers"])), ("avg_order_value", money(k["avg_order_value"])),
        ("avg_customer_revenue", money(k["avg_customer_revenue"])), ("avg_review_score", score(k["avg_review_score"])),
        ("repeat_purchase_rate", pct(k["repeat_purchase_rate"])), ("on_time_delivery_rate", pct(k["on_time_delivery_rate"])),
        ("late_delivery_rate", pct(k["late_delivery_rate"])),
    ]


def build_business_report(engine: Engine, f: Filters | None = None, include_opportunities: bool = True,
                          top_n: int = 10, now: datetime | None = None) -> Report:
    """Executive-level report for the filters ``f`` (None = everything)."""
    f = f or Filters()
    k = executive.calculate_executive_kpis(engine, f)
    kpis = pd.DataFrame([{"KPI": KPI_DEFINITIONS[key].label, "Value": val, "Definition": KPI_DEFINITIONS[key].tooltip().replace("\n", " | ")}
                         for key, val in _kpi_rows(k)])
    period = get_data_period(engine)
    monthly = revenue.calculate_monthly_revenue(engine, f)[["year_month", "revenue", "freight", "orders", "mom_growth_pct", "is_sparse"]]
    tables: dict[str, pd.DataFrame] = {
        "Monthly revenue": monthly,
        "Top categories": executive.get_top_categories(engine, f, top_n)[["category", "revenue", "orders", "revenue_share_pct"]],
        "Top states": executive.get_revenue_by_state(engine, f).head(top_n)[["state", "revenue", "orders", "revenue_share_pct"]],
        "Payment types": executive.get_payment_distribution(engine, f)[["payment_type", "orders", "revenue", "order_share_pct"]],
        "Delivery by state": logistics.analyze_delivery_by_state(engine, f).head(top_n),
    }
    findings: dict[str, list[Insight]] = {
        "Executive insights": executive.generate_executive_insights(engine, f),
        "Revenue": revenue.generate_revenue_recommendations(revenue.identify_revenue_opportunities(engine, f)),
        "Growth": growth.generate_growth_insights(engine, f),
    }
    if include_opportunities:
        opp = opportunities.find_business_opportunities(engine, f)
        tables["Opportunities"] = opp.head(25)
    return Report(
        title=f"{settings.APP_NAME} business report", generated_at=now or datetime.now(), filters_text=f.describe(),
        period_text=f"{period['first_day']} to {period['last_day']} ({period['orders']:,} orders loaded)",
        kpis=kpis, tables=tables, findings={k_: v for k_, v in findings.items() if v})
