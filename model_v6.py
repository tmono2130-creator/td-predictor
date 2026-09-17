"""
MODEL V6 — replaces the hand-weighted composite with a fitted model.

Compares three approaches on HELD-OUT data:
  1. Current composite (td_score -> calibration lookup) as the baseline
  2. Logistic regression (L2-regularized)
  3. Gradient boosting

Trains on all seasons except the held-out one, evaluates on the held-out
season only. This matters: the current calibration curve was fit on the
same 2025 data it was then evaluated against, which flatters it. Here
the test season is never seen during fitting or calibration.

Metrics:
  - Brier score (lower = better; the standard for probability quality)
  - Log loss (lower = better; punishes confident wrong answers harder)
  - AUC (ranking quality, independent of calibration)
  - Calibration table (do predicted %s match reality?)
  - Top-N hit rate (the practical "are my picks right" number)

USAGE:
    python -m pip install scikit-learn
    python build_training_data.py --seasons 2023 2024 2025
    python model_v6.py --holdout 2025

NOTE ON SAMPLE SIZE: roughly 2-3% of player-weeks are positives. That's
a rare-event problem -- regularization is on by default and you should
be suspicious of any model that looks dramatically better than the
others. If logistic regression and gradient boosting land close, prefer
logistic: it's interpretable and less prone to overfitting this kind of
sparse signal.
"""

import argparse

import numpy as np
import pandas as pd

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer
except ImportError:
    raise SystemExit("scikit-learn required. Run: python -m pip install scikit-learn")


EXCLUDE = {"player_id", "player", "team", "position", "opponent",
           "season", "week", "actual_td", "td_score", "td_estimate"}


def load_data(path):
    df = pd.read_csv(path)
    if "actual_td" not in df.columns:
        raise SystemExit(f"{path} has no actual_td column — regenerate with build_training_data.py")
    return df


def feature_columns(df):
    return [c for c in df.columns if c not in EXCLUDE and pd.api.types.is_numeric_dtype(df[c])]


def evaluate(name, y_true, y_prob, weeks=None):
    out = {
        "model": name,
        "brier": brier_score_loss(y_true, y_prob),
        "log_loss": log_loss(y_true, np.clip(y_prob, 1e-9, 1 - 1e-9)),
        "auc": roc_auc_score(y_true, y_prob) if len(set(y_true)) > 1 else float("nan"),
    }
    if weeks is not None:
        df = pd.DataFrame({"y": y_true, "p": y_prob, "week": weeks})
        for n in (10, 20, 30):
            hits = df.groupby("week", group_keys=False).apply(
                lambda g: g.nlargest(n, "p")["y"].sum()
            )
            out[f"top{n}_per_week"] = hits.mean()
    return out


def calibration_table(y_true, y_prob, bins=10):
    df = pd.DataFrame({"y": y_true, "p": y_prob})
    df["bucket"] = pd.qcut(df["p"], q=bins, duplicates="drop")
    return df.groupby("bucket", observed=True).agg(
        n=("y", "size"),
        avg_predicted_pct=("p", lambda x: x.mean() * 100),
        actual_rate_pct=("y", lambda x: x.mean() * 100),
    ).reset_index()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="training_data.csv")
    parser.add_argument("--holdout", type=int, required=True,
                         help="Season to hold out entirely for testing")
    args = parser.parse_args()

    df = load_data(args.data)
    feats = feature_columns(df)
    print(f"Loaded {len(df):,} rows, {len(feats)} features.")
    print(f"Positive rate: {df['actual_td'].mean() * 100:.2f}%")

    train = df[df["season"] != args.holdout].copy()
    test = df[df["season"] == args.holdout].copy()
    if train.empty or test.empty:
        raise SystemExit(f"Need data on both sides of the holdout. "
                          f"Seasons present: {sorted(df['season'].unique())}")

    print(f"\nTrain: {len(train):,} rows (seasons {sorted(train['season'].unique())})")
    print(f"Test:  {len(test):,} rows (season {args.holdout}, never seen in fitting)\n")

    imputer = SimpleImputer(strategy="median")
    X_train = imputer.fit_transform(train[feats])
    X_test = imputer.transform(test[feats])
    y_train, y_test = train["actual_td"].values, test["actual_td"].values
    test_weeks = test["week"].values

    results = []

    # --- Baseline: the current hand-weighted composite ------------------
    if "td_estimate" in test.columns:
        baseline_prob = np.clip(test["td_estimate"].values / 100.0, 1e-9, 1 - 1e-9)
        results.append(evaluate("Current composite", y_test, baseline_prob, test_weeks))

    # --- Logistic regression --------------------------------------------
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    logit = LogisticRegression(max_iter=2000, C=1.0)  # C=1.0 -> L2 regularization on
    logit.fit(X_train_s, y_train)
    logit_prob = logit.predict_proba(X_test_s)[:, 1]
    results.append(evaluate("Logistic regression", y_test, logit_prob, test_weeks))

    # --- Gradient boosting ----------------------------------------------
    gbm = HistGradientBoostingClassifier(
        max_depth=3, max_iter=200, learning_rate=0.05,
        l2_regularization=1.0, random_state=0,
    )
    gbm.fit(X_train, y_train)
    gbm_prob = gbm.predict_proba(X_test)[:, 1]
    results.append(evaluate("Gradient boosting", y_test, gbm_prob, test_weeks))

    # --- Report -----------------------------------------------------------
    print("=" * 78)
    print("MODEL COMPARISON (held-out season only)")
    print("=" * 78)
    res_df = pd.DataFrame(results)
    print(res_df.to_string(index=False))
    print("\nBrier and log_loss: LOWER is better. AUC and topN: HIGHER is better.")

    print("\n" + "=" * 78)
    print("LOGISTIC REGRESSION — FEATURE COEFFICIENTS")
    print("=" * 78)
    coefs = pd.Series(logit.coef_[0], index=feats).sort_values(key=abs, ascending=False)
    print(coefs.to_string())
    print("\n(Standardized coefficients — magnitude is comparable across features.")
    print(" Near-zero = the model found no use for it, even with it available.)")

    print("\n" + "=" * 78)
    print("CALIBRATION — best model by Brier score")
    print("=" * 78)
    best_idx = int(np.argmin([r["brier"] for r in results]))
    best_name = results[best_idx]["model"]
    best_prob = {"Current composite": baseline_prob if "td_estimate" in test.columns else logit_prob,
                  "Logistic regression": logit_prob,
                  "Gradient boosting": gbm_prob}[best_name]
    print(f"Best: {best_name}\n")
    print(calibration_table(y_test, best_prob).to_string(index=False))

    out_path = f"model_v6_predictions_{args.holdout}.csv"
    test_out = test[["player", "team", "position", "week", "actual_td"]].copy()
    test_out["logit_prob_pct"] = logit_prob * 100
    test_out["gbm_prob_pct"] = gbm_prob * 100
    if "td_estimate" in test.columns:
        test_out["current_model_pct"] = test["td_estimate"].values
    test_out.to_csv(out_path, index=False)
    print(f"\nPer-player predictions saved to: {out_path}")

    print("\nIF a fitted model wins clearly on Brier AND top-N, that's your case for")
    print("replacing the hand-weighted composite. If they're close, prefer logistic")
    print("regression (interpretable, less overfit-prone on a ~2-3% positive rate),")
    print("and consider that the current composite holding its own is a real result too.")


if __name__ == "__main__":
    main()