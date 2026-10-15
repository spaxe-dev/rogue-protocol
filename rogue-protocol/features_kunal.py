"""Promoted feature preprocessing for the Rogue Protocol log classifier.

Fit on training rows only; transform validation/test with the fitted pipeline.
"""

import re

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler


NUMERIC = [
    "reading", "delay_ms", "retry_count", "mlen", "reading_missing",
    "has_red", "calm", "pos0", "pos1", "pos2",
    "neg0", "neg1", "neg2", "neg3", "neg4",
]
CATEGORICAL = ["module", "mode", "node", "status"]
CALM_PHRASES = re.compile(r"all is well|nothing to see|crew need not worry", re.IGNORECASE)
PHRASE_FLAGS = {
    "pos0": "seal breach",
    "pos1": "heartbeat missing",
    "pos2": "queue overflow",
    "neg0": "drill",
    "neg1": "duplicate of earlier",
    "neg2": "recovered after retry",
    "neg3": "scheduled calibration",
    "neg4": "self-test pattern",
}


def _as_frame(rows):
    """Copy input rows and create safe text/numeric helper columns."""
    if not isinstance(rows, pd.DataFrame):
        rows = pd.DataFrame(rows)
    df = rows.copy()
    if "message" not in df:
        raise ValueError("input rows must include a 'message' column")

    # Tolerate nulls and malformed byte strings so one damaged log cannot
    # break vectorization.
    def clean_message(value):
        if value is None or (not isinstance(value, (bytes, bytearray)) and pd.isna(value)):
            return ""
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="replace")
        return str(value)

    message = df["message"].map(clean_message)
    df["message"] = message
    df["mlen"] = message.str.len().astype(float)
    df["calm"] = message.map(lambda value: int(bool(CALM_PHRASES.search(value))))
    df["has_red"] = message.str.contains("REDACTED", regex=False).astype(int)
    lowered = message.str.lower()
    for column, phrase in PHRASE_FLAGS.items():
        df[column] = lowered.str.contains(phrase, regex=False).astype(int)

    if "reading" not in df:
        df["reading"] = np.nan
    reading = pd.to_numeric(df["reading"], errors="coerce")
    df["reading_missing"] = reading.isna().astype(float)
    df["reading"] = reading
    for column in ("delay_ms", "retry_count"):
        if column not in df:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in CATEGORICAL:
        if column not in df:
            df[column] = "__missing__"
        df[column] = df[column].fillna("__missing__").astype(str)
    return df


def make_preprocessor(dense=False):
    """Build a train-fit-only preprocessing pipeline.

    Args:
        dense: Retained for compatibility with the current training script.
            The promoted spec uses the same dense SVD-64 representation for
            every model path.
    """
    del dense
    text_features = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=8000, ngram_range=(1, 2),
                                  min_df=2, sublinear_tf=True)),
        ("svd", TruncatedSVD(n_components=64, random_state=42)),
    ])

    columns = ColumnTransformer(
        transformers=[
            ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("text", text_features, "message"),
        ],
        # The SVD text block and numeric/categorical features form a dense matrix.
        sparse_threshold=0.0,
    )
    return Pipeline([
        ("derive", FunctionTransformer(_as_frame, validate=False)),
        ("columns", columns),
    ])
