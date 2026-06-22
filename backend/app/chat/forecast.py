"""
Lightweight forecasting — pure-Python OLS linear regression with a simple
confidence band. No numpy/scipy dependency (keeps the demo install light and
avoids Windows build friction).

Given historical (period, value) points, project `periods_ahead` future points.
"""

from __future__ import annotations

import math


def linear_forecast(values: list[float], periods_ahead: int = 3) -> dict:
    n = len(values)
    if n < 2:
        return {"history": values, "forecast": [], "slope": 0.0, "ci": []}

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n

    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x

    # residual standard error for a simple band
    resid = [y - (intercept + slope * x) for x, y in zip(xs, values)]
    dof = max(n - 2, 1)
    se = math.sqrt(sum(r * r for r in resid) / dof)

    forecast: list[float] = []
    ci: list[dict] = []
    for k in range(1, periods_ahead + 1):
        x = n - 1 + k
        yhat = intercept + slope * x
        margin = 1.96 * se * math.sqrt(1 + 1 / n + (x - mean_x) ** 2 / sxx) if sxx else 1.96 * se
        forecast.append(round(yhat, 2))
        ci.append({"lower": round(yhat - margin, 2), "upper": round(yhat + margin, 2)})

    pct = (slope / mean_y * 100) if mean_y else 0.0
    return {
        "history": values,
        "forecast": forecast,
        "slope": round(slope, 4),
        "trend_pct_per_period": round(pct, 2),
        "ci": ci,
    }
