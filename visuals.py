"""
Generates chart images (as PNG bytes) for embedding in the email report.
Uses matplotlib's non-interactive backend, no display needed.
"""

import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GREEN = "#1a7a3c"
ORANGE = "#f5a623"
GRAY = "#5f5e5a"


def _fig_to_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def cumulative_points_chart(my_history, rival_history):
    my_points = [gw["total_points"] for gw in my_history["current"]]
    rival_points = [gw["total_points"] for gw in rival_history["current"]]
    gws = list(range(1, len(my_points) + 1))

    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.plot(gws, my_points, marker="o", color=GREEN, linewidth=2, label="You")
    ax.plot(gws[:len(rival_points)], rival_points, marker="o", color=ORANGE, linewidth=2, label="Rank 1")
    ax.set_xlabel("Gameweek")
    ax.set_ylabel("Cumulative points")
    ax.set_title("Cumulative points: you vs. rank 1")
    ax.legend()
    ax.grid(alpha=0.3)
    return _fig_to_bytes(fig)


def gap_bar_chart(my_history, rival_history):
    my_points = [gw["total_points"] for gw in my_history["current"]]
    rival_points = [gw["total_points"] for gw in rival_history["current"]]
    n = min(len(my_points), len(rival_points))
    gaps = [rival_points[i] - my_points[i] for i in range(n)]
    gws = list(range(1, n + 1))

    fig, ax = plt.subplots(figsize=(6, 3))
    colors = [ORANGE if g > 0 else GREEN for g in gaps]
    ax.bar(gws, gaps, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Gameweek")
    ax.set_ylabel("Gap (rank 1 − you)")
    ax.set_title("Weekly gap to rank 1 (orange = they're ahead)")
    ax.grid(alpha=0.3, axis="y")
    return _fig_to_bytes(fig)


def transfer_options_chart(suggestions_by_profile):
    profiles = list(suggestions_by_profile.keys())
    net_gains = []
    for profile in profiles:
        suggestions = suggestions_by_profile[profile]
        net_gains.append(suggestions[0]["net_gain"] if suggestions else 0)

    fig, ax = plt.subplots(figsize=(6, 3))
    colors = [GREEN if g > 0 else GRAY for g in net_gains]
    ax.bar(profiles, net_gains, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Best net gain (pts)")
    ax.set_title("Best available transfer, by strategy profile")
    ax.grid(alpha=0.3, axis="y")
    return _fig_to_bytes(fig)
