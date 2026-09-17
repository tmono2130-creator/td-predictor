"""
TRAIN FINAL MODEL — fits the production logistic regression on ALL
available training data and saves it for the live app to use.

This is different from model_v6.py: that script held out a season to
test whether a fitted model beats the composite (it did, and logistic
specifically won on top-10 hit rate). This script trains the model
that actually gets used, on every row available -- no holdout, since
the methodology is already validated.

Logistic was chosen over gradient boosting per the model_v6.py
comparison: close on Brier/log-loss, logistic clearly better on top-10
hit rate, and it's the more interpretable, less overfit-prone choice
for a ~2-6% positive-rate problem.

USAGE:
    python train_final_model.py --data training_data.csv

RUN THIS AGAIN whenever training_data.csv is refreshed (i.e. after
regenerating it with a newly-completed week added) -- the app always
uses whatever's in model_v6.joblib, so the model only gets smarter
after you retrain it.
"""

import argparse

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

EXCLUDE = {"player_id", "player", "team", "position", "opponent",
           "season", "week", "actual_td", "td_score", "td_estimate"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="training_data.csv")
    parser.add_argument("--out", type=str, default="model_v6.joblib")
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    feats = [c for c in df.columns if c not in EXCLUDE and pd.api.types.is_numeric_dtype(df[c])]

    print(f"Training on {len(df):,} rows, {len(feats)} features, "
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