"""Display helpers: headers, banners, tables, and charts for the notebooks."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

try:
    from IPython.display import display, Markdown, HTML
except ImportError:  # pragma: no cover - allows import outside Jupyter
    display = print  # type: ignore

    def Markdown(text):  # type: ignore
        return text

    def HTML(text):  # type: ignore
        return text


def header(text: str, level: int = 2) -> None:
    """Render a markdown-style header in a notebook (or print it plainly)."""
    display(Markdown(f"{'#' * level} {text}"))


def banner(text: str, kind: str = "info") -> None:
    """Render a short highlighted status line.

    kind: one of "info", "success", "warning", "error"
    """
    colors = {
        "info": "#0969da",
        "success": "#1a7f37",
        "warning": "#9a6700",
        "error": "#cf222e",
    }
    color = colors.get(kind, colors["info"])
    display(
        HTML(
            f'<div style="border-left:4px solid {color}; padding:6px 12px; '
            f'margin:6px 0; background:#f6f8fa;"><strong>{text}</strong></div>'
        )
    )


def show_table(rows: Iterable[Dict[str, Any]], columns: Optional[List[str]] = None):
    """Render a list of dicts as a pandas DataFrame table."""
    import pandas as pd

    rows = list(rows)
    if not rows:
        display(Markdown("_No data to display._"))
        return None
    df = pd.DataFrame(rows)
    if columns:
        df = df[[c for c in columns if c in df.columns]]
    display(df)
    return df


def mask_key_in_url(url: str, key: str) -> str:
    """Return `url` with any occurrence of the secret `key` masked out."""
    if not key:
        return url
    return url.replace(key, "***MASKED***")


def plot_remaining_tokens(requests_log: List[Dict[str, Any]], trip_index: Optional[int] = None):
    """Plot remaining-tokens-per-minute across a sequence of requests."""
    import matplotlib.pyplot as plt

    xs = [r.get("request_number") for r in requests_log]
    ys = [r.get("remaining_tokens") for r in requests_log]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(xs, ys, marker="o", label="remaining-tokens")
    if trip_index is not None:
        ax.axvline(trip_index, color="red", linestyle="--", label="429 tripped")
    ax.set_xlabel("Request #")
    ax.set_ylabel("Remaining tokens (TPM window)")
    ax.set_title("Remaining tokens per request")
    ax.legend()
    plt.tight_layout()
    plt.show()
    return fig


def plot_token_series_by_dimension(
    rows: Iterable[Dict[str, Any]],
    dimension_name: str = "ClientApp",
    metric_name: str = "total_tokens",
):
    """Plot token metric time series split by one dimension."""
    import matplotlib.pyplot as plt
    import pandas as pd

    df = pd.DataFrame(list(rows))
    if df.empty:
        display(Markdown("_No token metric rows to plot yet._"))
        return None

    df = df[df["metric_name"] == metric_name].copy()
    if df.empty:
        display(Markdown(f"_No rows found for metric `{metric_name}`._"))
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    pivot = df.pivot_table(
        index="timestamp",
        columns="dimension_value",
        values="total",
        aggfunc="sum",
        fill_value=0,
    ).sort_index()

    fig, ax = plt.subplots(figsize=(8, 4))
    if len(pivot.index) == 1:
        # A single 5-minute bin cannot form a time axis; show the split as bars instead.
        pivot.iloc[0].plot.bar(ax=ax, color=[f"C{i}" for i in range(len(pivot.columns))])
        ax.set_xlabel(f"{dimension_name} (5-minute bin starting {pivot.index[0]:%Y-%m-%d %H:%M} UTC)")
        ax.tick_params(axis="x", rotation=0)
    else:
        pivot.plot(ax=ax, marker="o")
        ax.set_xlabel("5-minute bin")
        ax.legend(title=dimension_name)
    ax.set_ylabel("Tokens")
    ax.set_ylim(bottom=0)
    ax.set_title(f"{metric_name} by {dimension_name}")
    plt.tight_layout()
    plt.show()
    return fig
