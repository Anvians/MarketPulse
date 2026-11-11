"""Review-comment term analysis (Portuguese).

This is **not a sentiment model**. Without a validated Portuguese sentiment model or labelled data,
inventing one would be guesswork. The review *score* already labels each comment, so we ask a
transparent question: which words are over-represented in comments of negative (score 1-2) vs positive
(score 4-5) reviews? Method: binary word occurrence per comment, smoothed log-odds ratio
(add-one prior) between the two groups, terms must appear in at least ``TEXT_MIN_TERM_COUNT``
comments. Stopwords are a small built-in Portuguese list. Terms are shown in the original language
(not translated). Most reviews have no comment, so this describes commenters only.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer
from sqlalchemy.engine import Engine

from analytics.base import Filters, order_scope, read_sql
from config import settings

PT_STOPWORDS = frozenset("""
a o as os um uma uns umas de do da dos das em no na nos nas por para pra com sem sob sobre entre ate ao aos
e ou mas que se como mais menos muito muita muitos muitas ja nao sim foi era ser estar esta estou estava
tem tinha ter tive meu minha meus minhas seu sua seus suas isso isto esse essa esses essas este estas aquele
aquela eu ele ela eles elas nos voce vcs me te lhe lhes mim ti la ai aqui tudo todo toda todos todas so tambem
bem mal ate quando onde porque pois pelo pela pelos pelas dia dias vez vezes ainda ha foram fui sao vai vou
mesmo mesma apos antes depois nem num numa produto produtos comprei recebi
""".split())


def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Lowercase, remove accents and non-letters (so 'não' and 'nao' are one term)."""
    return re.sub(r"[^a-z\s]", " ", _strip_accents(str(text).lower()))


def load_comments(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Reviews (one per order) with a non-empty comment: review_score, comment."""
    s = order_scope(f)
    return read_sql(
        engine,
        "SELECT r.review_score, fr.review_comment_message AS comment\n"
        f"FROM {s.from_sql}\nJOIN vw_order_review r ON r.order_id = o.order_id\n"
        "JOIN fact_reviews fr ON fr.review_id = r.review_id AND fr.order_id = r.order_id\n"
        f"{s.where('fr.review_comment_message IS NOT NULL', 'btrim(fr.review_comment_message) <> ' + chr(39) * 2)}", s.params)


def term_association(comments: pd.DataFrame, min_count: int = settings.TEXT_MIN_TERM_COUNT, top_n: int = 15) -> dict:
    """Terms most associated with negative vs positive reviews.

    ``comments``: columns review_score, comment. Returns ``available``, counts of negative / positive
    comments, ``negative_terms`` and ``positive_terms`` (term, negative_comments, positive_comments,
    log_odds; positive log_odds = more typical of NEGATIVE reviews in ``negative_terms``)."""
    out = {"available": False, "reason": None, "n_negative": 0, "n_positive": 0,
           "negative_terms": pd.DataFrame(), "positive_terms": pd.DataFrame()}
    c = comments.dropna(subset=["comment"]).copy()
    neg = c[c["review_score"] <= 2]
    pos = c[c["review_score"] >= 4]
    out["n_negative"], out["n_positive"] = int(len(neg)), int(len(pos))
    if len(neg) < 20 or len(pos) < 20:
        out["reason"] = "Needs at least 20 negative and 20 positive comments for the current filters."
        return out
    vec = CountVectorizer(preprocessor=normalize, stop_words=sorted(PT_STOPWORDS), binary=True, min_df=min_count, token_pattern=r"(?u)\b[a-z]{3,}\b")
    try:
        x = vec.fit_transform(pd.concat([neg["comment"], pos["comment"]]))
    except ValueError:
        out["reason"] = f"No term appears in at least {min_count} comments."
        return out
    terms = vec.get_feature_names_out()
    n_neg_docs = len(neg)
    cn = np.asarray(x[:n_neg_docs].sum(axis=0)).ravel()
    cp = np.asarray(x[n_neg_docs:].sum(axis=0)).ravel()
    lo = np.log((cn + 1) / (len(neg) - cn + 1)) - np.log((cp + 1) / (len(pos) - cp + 1))
    df = pd.DataFrame({"term": terms, "negative_comments": cn, "positive_comments": cp, "log_odds": lo})
    out.update(available=True,
               negative_terms=df.sort_values("log_odds", ascending=False).head(top_n).reset_index(drop=True),
               positive_terms=df.sort_values("log_odds").head(top_n).reset_index(drop=True))
    return out


def comment_coverage(engine: Engine, f: Filters | None = None) -> dict:
    """Share of reviews that carry a comment, and their average scores with / without."""
    s = order_scope(f)
    df = read_sql(
        engine,
        "SELECT (fr.review_comment_message IS NOT NULL AND btrim(fr.review_comment_message) <> '') AS has_comment, "
        "COUNT(*) AS reviews, AVG(r.review_score) AS avg_score\n"
        f"FROM {s.from_sql}\nJOIN vw_order_review r ON r.order_id = o.order_id\n"
        f"JOIN fact_reviews fr ON fr.review_id = r.review_id AND fr.order_id = r.order_id\n{s.where()}\nGROUP BY 1", s.params)
    total = float(df["reviews"].sum())
    with_c = df[df["has_comment"]]
    without = df[~df["has_comment"]]
    return {"reviews": int(total), "with_comment_share": float(with_c["reviews"].sum() / total) if total else None,
            "avg_score_with_comment": float(with_c["avg_score"].iloc[0]) if len(with_c) else None,
            "avg_score_without_comment": float(without["avg_score"].iloc[0]) if len(without) else None}
