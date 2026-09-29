#!/usr/bin/env python3
"""Plot cumulative ASR over 12 iterations for manually entered models.

Each ``loop_success_ratio`` value is the proportion of all eventually
successful samples whose first success happened in that loop. Therefore:

    ASR_at_loop_k = cumulative_ratio_through_loop_k * final_success_rate

The ratios are normalized when their sum is close to 1.0. This is useful when
the manually entered values have been rounded, while still rejecting data that
is likely incomplete or incorrect.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR / "cumulative_asr_by_iteration.png"
LOOP_COUNT = 12
NORMALIZE_SUM_TOLERANCE = 0.02


# Enter proportions as decimals, not percentages:
# 0.35 means 35% of the eventually successful samples.
models = {
    "Claude-Sonnet-4.6": {
        "loop_success_ratio": [
            0.1786,  # loop 1
            0.1310,  # loop 2
            0.1071,  # loop 3
            0.1310,  # loop 4
            0.1190,  # loop 5
            0.0833,  # loop 6
            0.0476,  # loop 7
            0.0476,  # loop 8
            0.0595,  # loop 9
            0.0357,  # loop 10
            0.0357,  # loop 11
            0.0238,  # loop 12
        ],
        "final_success_rate": 0.4444,
        "color": "#E64B35",
        "marker": "o",
    },
    "DeepSeek-V4-Flash": {
        "loop_success_ratio": [
            0.2969,
            0.1719,
            0.0703,
            0.0547,
            0.1094,
            0.0781,
            0.0469,
            0.0312,
            0.0391,
            0.0625,
            0.0234,
            0.0156,
        ],
        "final_success_rate": 0.7619,
        "color": "#4DBBD5",
        "marker": "^",
    },
    "GLM-5.3-Flash": {
        "loop_success_ratio": [
            0.25,
            0.1442,
            0.0769,
            0.1154,
            0.0769,
            0.0577,
            0.0577,
            0.0481,
            0.0481,
            0.0385,
            0.0288,
            0.0577,
        ],
        "final_success_rate": 0.5123,
        "color": "#00A087",
        "marker": "s",
    },
}


def cumulative_asr(
    model_name: str,
    loop_success_ratio: list[float],
    final_success_rate: float,
) -> np.ndarray:
    """Return ASR percentages at each loop after validating the input."""
    ratios = np.asarray(loop_success_ratio, dtype=float)

    if ratios.size != LOOP_COUNT:
        raise ValueError(
            f"{model_name}: loop_success_ratio must contain "
            f"{LOOP_COUNT} values, got {ratios.size}."
        )
    if not np.all(np.isfinite(ratios)):
        raise ValueError(f"{model_name}: loop_success_ratio contains non-finite values.")
    if np.any(ratios < 0):
        raise ValueError(f"{model_name}: loop_success_ratio cannot contain negative values.")
    if not 0 <= final_success_rate <= 1:
        raise ValueError(
            f"{model_name}: final_success_rate must be between 0 and 1, "
            f"got {final_success_rate}."
        )

    ratio_sum = float(ratios.sum())
    if ratio_sum <= 0:
        raise ValueError(f"{model_name}: loop_success_ratio must sum to a positive value.")
    if not np.isclose(ratio_sum, 1.0, atol=1e-9):
        if abs(ratio_sum - 1.0) > NORMALIZE_SUM_TOLERANCE:
            raise ValueError(
                f"{model_name}: loop_success_ratio sums to {ratio_sum:.6f}. "
                "Check the manually entered data; the deviation is too large "
                "to treat as rounding."
            )
        print(
            f"WARNING: {model_name} ratio sum is {ratio_sum:.6f}; "
            "normalizing the ratios so loop 12 equals the final ASR."
        )
        ratios = ratios / ratio_sum

    return np.cumsum(ratios) * final_success_rate * 100


def main() -> None:
    iterations = np.arange(1, LOOP_COUNT + 1)

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 13,
            "axes.labelsize": 17,
            "axes.labelweight": "bold",
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
            "legend.fontsize": 14,
        }
    )

    fig, ax = plt.subplots(figsize=(8.0, 5.3))

    for model_name, config in models.items():
        asr_by_loop = cumulative_asr(
            model_name=model_name,
            loop_success_ratio=config["loop_success_ratio"],
            final_success_rate=config["final_success_rate"],
        )

        print(f"\n{model_name}")
        print("-" * 40)
        for loop, asr in zip(iterations, asr_by_loop):
            print(f"Loop {loop:2d}: ASR = {asr:6.2f}%")

        ax.plot(
            iterations,
            asr_by_loop,
            label=model_name,
            color=config["color"],
            marker=config["marker"],
            linewidth=2.6,
            markersize=7.5,
            markeredgecolor="white",
            markeredgewidth=1.2,
        )
        ax.annotate(
            f"{asr_by_loop[-1]:.1f}%",
            xy=(LOOP_COUNT, asr_by_loop[-1]),
            xytext=(7, 0),
            textcoords="offset points",
            fontsize=15,
            fontweight="bold",
            color=config["color"],
            va="center",
        )

    ax.set_xlabel("Iteration")
    ax.set_ylabel("Attack Success Rate (%)")
    ax.set_xticks(iterations)

    max_final_asr = max(config["final_success_rate"] for config in models.values()) * 100
    upper_limit = min(100, max(10, np.ceil(max_final_asr / 10) * 10 + 5))
    ax.set_ylim(0, upper_limit)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.grid(True, linestyle="-", linewidth=0.8, alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
