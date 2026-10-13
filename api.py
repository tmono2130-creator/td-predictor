import math
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from td_predictor_v5 import get_predictions


app = FastAPI(
    title="NFL TD Predictor API",
    description="API for the existing NFL Touchdown Likelihood Predictor.",
    version="1.0.0",
)


# Allow the local Next.js website to communicate with the Python API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def clean_value(value: Any) -> Any:
    """Convert pandas and NumPy values into JSON-safe Python values."""

    if value is None:
        return None

    # Convert NumPy scalar values to standard Python values.
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass

    # Replace missing values with JSON null.
    try:
        if pd.isna(value):
            return None
    except (ValueError, TypeError):
        pass

    # Prevent NaN and infinity from breaking JSON responses.
    if isinstance(value, float) and not math.isfinite(value):
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


@app.get("/")
def home():
    """Confirm that the API is running."""

    return {
        "message": "NFL TD Predictor API is running.",
        "documentation": "/docs",
        "predictions_endpoint": "/api/predictions",
    }


@app.get("/health")
def health():
    """Check whether the API server is responding."""

    return {"status": "ok"}


@app.get("/api/predictions")
def predictions(
    season: int = Query(default=2026, ge=1999, le=2100),
    week: int = Query(default=1, ge=1, le=18),
    top: int = Query(default=30, ge=1, le=500),
):
    """
    Run the existing prediction engine and return its highest-ranked players.

    Example:
    /api/predictions?season=2026&week=2&top=30
    """

    try:
        # Call the existing prediction engine without modifying it.
        scored, matchups = get_predictions(season, week)

        if scored is None or scored.empty:
            raise HTTPException(
                status_code=404,
                detail="The prediction engine returned no players.",
            )

        # Use the model's existing ranking and ordering.
        results = scored.head(top)

        players = []

        for rank, (_, row) in enumerate(results.iterrows(), start=1):
            player = {
                str(key): clean_value(value)
                for key, value in row.to_dict().items()
            }

            player["rank"] = rank
            players.append(player)

        safe_matchups = {
            str(key): clean_value(value)
            for key, value in matchups.items()
        }

        return {
            "season": season,
            "week": week,
            "count": len(players),
            "players": players,
            "matchups": safe_matchups,
            "notice": (
                "TD estimates are model estimates, not guaranteed outcomes."
            ),
        }

    except HTTPException:
        raise

    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # Detailed errors appear in the PowerShell terminal.
        print(
            f"Prediction API error: "
            f"{type(exc).__name__}: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "The prediction engine encountered an error. "
                "Check the API terminal for details."
            ),
        ) from exc
