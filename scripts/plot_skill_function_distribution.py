#!/usr/bin/env python3
"""Plot the three-part percentage distribution of six skill categories."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter


SCRIPT_DIR = Path(__file__).resolve().parent
PNG_OUTPUT = SCRIPT_DIR / "skill_function_distribution.png"
PDF_OUTPUT = SCRIPT_DIR / "skill_function_distribution.pdf"
EXPECTED_CATEGORY_COUNT = 6


# Enter percentages directly. For example, 35.2 means 35.2%.
categories = [
    "Business / Marketing",
    "Data / Analysis / Report",
    "Design / Web / QA",
    "Knowledge Management",
    "Templates / Publishing",
    "Software / Automation",
]

# Bottom layer: gray
gray_values = np.array(
    [
        57.14,
        61.04,
        62.99,
        52.38,
        58.93,
        60.71,
    ],
    dtype=float,
)

# Middle layer: light green
green_values = np.array(
    [
        28.57,
        32.47,
        29.22,
        23.81,
        34.82,
        21.43,
    ],
    dtype=float,
)

# Top layer: light red
red_values = np.array(
    [
        14.29,
        6.49,
        7.79,
        23.81,
        6.25,
        17.86,
    ],
    dtype=float,
)


# Replace these with the meanings of your three layers.
gray_label = "Steering-Only Success"
green_label = "Coordinated Success"
red_label = "Fail"


def validate_data() -> None:
    """Validate that every category has three percentages summing to 100."""
    values = {
        "gray_values": gray_values,
        "green_values": green_values,
        "red_values": red_values,
    }

    if len(categories) != EXPECTED_CATEGORY_COUNT:
        raise ValueError(
            f"categories must contain {EXPECTED_CATEGORY_COUNT} items, "
            f"got {len(categories)}."
        )

    for name, array in values.items():
        if len(array) != len(categories):
            raise ValueError(
                f"{name} must contain {len(categories)} values, got {len(array)}."
            )
        if not np.all(np.isfinite(array)):
            raise ValueError(f"{name} contains non-finite values.")
        if np.any(array < 0):
            raise ValueError(f"{name} cannot contain negative values.")

    totals = gray_values + green_values + red_values
    if not np.allclose(totals, 100.0, atol=1e-6):
        details = ", ".join(
            f"{categories[i].replace(chr(10), ' ')}={totals[i]:.2f}%"
            for i in range(len(categories))
            if not np.isclose(totals[i], 100.0, atol=1e-6)
        )
        raise ValueError(
            "Each category's gray + green + red values must sum to 100%. "
            f"Incorrect totals: {details}"
        )


def add_center_labels(
    ax: plt.Axes,
    x: np.ndarray,
    values: np.ndarray,
    bottoms: np.ndarray,
) -> None:
    """Place a percentage label in the center of each non-empty segment."""
    for index, value in enumerate(values):
        if value <= 0:
            continue
        ax.text(
            x[index],
            bottoms[index] + value / 2,
            f"{value:.1f}%",
            ha="center",
            va="center",
            fontsize=14,
            fontweight="bold",
        )


def main() -> None:
    validate_data()

    x = np.arange(len(categories))
    bar_width = 0.68

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 14,
            "axes.labelsize": 17,
            "axes.labelweight": "bold",
            "xtick.labelsize": 14,
            "ytick.labelsize": 14,
            "legend.fontsize": 16,
        }
    )

    fig, ax = plt.subplots(figsize=(9.5, 6.2))

    ax.bar(
        x,
        gray_values,
        width=bar_width,
        label=gray_label,
        color="#BDBDBD",
        edgecolor="white",
        linewidth=1.0,
    )
    ax.bar(
        x,
        green_values,
        width=bar_width,
        bottom=gray_values,
        label=green_label,
        color="#A8DDB5",
        edgecolor="white",
        linewidth=1.0,
    )
    ax.bar(
        x,
        red_values,
        width=bar_width,
        bottom=gray_values + green_values,
        label=red_label,
        color="#F4A6A6",
        edgecolor="white",
        linewidth=1.0,
    )

    add_center_labels(ax, x, gray_values, np.zeros_like(gray_values))
    add_center_labels(ax, x, green_values, gray_values)
    add_center_labels(ax, x, red_values, gray_values + green_values)

    ax.set_ylabel("Percentage (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(
        categories,
        rotation=30,
        ha="right",
        rotation_mode="anchor",
    )
    ax.set_ylim(0, 100)
    ax.set_yticks(np.arange(0, 101, 20))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))

    ax.grid(axis="y", linestyle="-", linewidth=0.8, alpha=0.25)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(1.2)
    ax.spines["bottom"].set_linewidth(1.2)

    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.12),
        ncol=3,
        frameon=False,
    )

    fig.tight_layout()
    fig.savefig(PNG_OUTPUT, dpi=300, bbox_inches="tight")
    fig.savefig(PDF_OUTPUT, bbox_inches="tight")
    plt.close(fig)

    print(f"PNG saved to: {PNG_OUTPUT}")
    print(f"PDF saved to: {PDF_OUTPUT}")


if __name__ == "__main__":
    main()
