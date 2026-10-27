"""
TRAIN THE OPTIONAL FITTED MODEL from validated historical training data.

This script does not prove that logistic regression beats the V5 composite.
Run the guarded, strictly chronological model_v6.py evaluation first, inspect
its held-out results, and only then decide whether to train/deploy a candidate.
The V5 model remains the default when no local model bundle is present.
"""

import argparse

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from evaluation_utils import validate_training_data_frame

EXCLUDE = {"player_id", "game_id", "player", "team", "position", "opponent",
           "season", "week", "actual_td", "td_score", "td_estimate",
           "week_complete", "prediction_origin", "prediction_generated_at",
           "feature_cutoff_season", "feature_cutoff_week"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="training_data.csv")
    parser.add_argument("--out", type=str, default="model_v6.joblib")
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    try:
        validate_training_data_frame(df)
    except ValueError as e:
        raise SystemExit(f"Training data is not valid: {e}") from e
    feats = [c for c in df.columns if c not in EXCLUDE and pd.api.types.is_numeric_dtype(df[c])]

    print(f"Training on {len(df):,} retrospective rows, {len(feats)} features, "
          f"seasons {sorted(df['season'].unique().tolist())}")
    print(f"Positive rate: {df['actual_td'].mean() * 100:.2f}%")

    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(df[feats])
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    y = df["actual_td"].values

    model = LogisticRegression(max_iter=2000, C=1.0)
    model.fit(X_scaled, y)

    joblib.dump({
        "model": model,
        "scaler": scaler,
        "imputer": imputer,
        "features": feats,
        "trained_on_seasons": sorted(df["season"].unique().tolist()),
        "n_rows": len(df),
    }, args.out)

    coefs = pd.Series(model.coef_[0], index=feats).sort_values(key=abs, ascending=False)
    print(f"\nSaved to {args.out}\n")
    print("Top features by |coefficient|:")
    print(coefs.head(10).to_string())


if __name__ == "__main__":
    main()