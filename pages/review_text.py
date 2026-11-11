"""Review Text Analysis: which words go with bad or good reviews (not a sentiment model)."""
import streamlit as st

from analytics import text_analysis as ta
from components import charts, data
from components.filters import current
from components.formatting import number, pct, score
from components.layout import page_header
from config import settings

f = current()
page_header("Review Text Analysis", "Which words are over-represented in comments of low-scoring vs high-scoring reviews. Comments are in Portuguese and are shown untranslated.")
st.info("This is **not** a sentiment model. The review score already labels each comment, so we measure which words are more typical of negative (1–2 stars) "
        "or positive (4–5 stars) comments. Only reviewers who wrote a comment are included, and they are not a random sample of all customers.")

cov = data.q(ta.comment_coverage, f)
a, b, c = st.columns(3)
a.metric("Reviews", number(cov["reviews"]), border=True)
b.metric("With a written comment", pct(cov["with_comment_share"]), border=True)
c.metric("Avg score: with vs without comment", f"{score(cov['avg_score_with_comment'])} vs {score(cov['avg_score_without_comment'])}", border=True,
         help="Reviewers who write comments tend to score differently from those who do not.")

comments = data.q(ta.load_comments, f)
res = ta.term_association(comments)
if not res["available"]:
    st.info(res["reason"])
    st.stop()
st.caption(f"{res['n_negative']:,} negative and {res['n_positive']:,} positive comments. Terms must appear in at least {settings.TEXT_MIN_TERM_COUNT} comments. "
           "Log-odds: how much more often a term appears in one group (0 = equally often; 1 ≈ 2.7× as likely).")
x, y = st.columns(2)
with x:
    n = res["negative_terms"]
    charts.chart_card("Words typical of negative reviews", charts.bar_fig(n, "term", "log_odds"), n, "rt_neg")
with y:
    p = res["positive_terms"].assign(log_odds=lambda d: -d["log_odds"])
    charts.chart_card("Words typical of positive reviews", charts.bar_fig(p, "term", "log_odds"), p, "rt_pos")
st.caption("Read the words in context before drawing conclusions: a word can mark a complaint (e.g. 'atrasou' = was late) or a topic customers merely mention.")
