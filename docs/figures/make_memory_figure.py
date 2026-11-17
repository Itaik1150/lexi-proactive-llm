"""
Draws the memory design of Lexi as a figure (docs/REVIEW.md M1-M5).

    python docs/figures/make_memory_figure.py

Writes memory_design.pdf (vector, for LaTeX), memory_design.svg (editable) and memory_design.png
(preview / slides) next to this file. Edit the texts below and run it again to update the figure.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

INK = "#0b0b0b"        # text
MUTED = "#52514e"      # secondary text, arrows, neutral borders
NEUTRAL = ("#f4f4f2", "#52514e")   # (fill, border): process steps
STORE = ("#e6eff9", "#2a78d6")     # what is stored
CHAT = ("#e3f5ee", "#168f64")      # use in the conversation
NOTIFY = ("#fdeae2", "#d2551f")    # use in the notification

fig, ax = plt.subplots(figsize=(7.4, 8.3))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x0, y0, x1, y1, style, title, body, centered=False):
    fill, edge = style
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=1.4",
                                facecolor=fill, edgecolor=edge, linewidth=1.3))
    ax.text((x0 + x1) / 2, y1 - 1.6, title, ha="center", va="top", fontsize=9.6, fontweight="bold", color=INK)
    if centered:
        ax.text((x0 + x1) / 2, y1 - 5.6, body, ha="center", va="top", fontsize=8.0, color=INK, linespacing=1.35)
    else:
        ax.text(x0 + 2.2, y1 - 5.6, body, ha="left", va="top", fontsize=8.0, color=INK, linespacing=1.35)


def arrow(start, end, dashed=False):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=13, linewidth=1.3, color=MUTED,
                                 linestyle=(0, (4, 3)) if dashed else "solid", shrinkA=0, shrinkB=0))


# 1. when
box(22, 90.5, 78, 98.5, NEUTRAL, "A conversation ends",
    "Finish button, or 30 minutes without a message", centered=True)

# 2. building
box(12, 70, 88, 85.5, NEUTRAL, "Memory builder (identical in all three conditions)",
    "One language-model call per finished conversation.\n"
    "Only what the participant wrote is used; no speculation.\n"
    "Each conversation is stored exactly once.", centered=True)

# 3. what is stored
box(4, 49.5, 46, 63.5, STORE, "Dated summary",
    "One per conversation, 2-4 sentences,\n"
    "with the date of the conversation.")
box(54, 49.5, 96, 63.5, STORE, "Scored events",
    "0-5 per conversation: event, feeling,\n"
    "when, a short reason, score 1-10.")

# 4. how it is used
box(4, 19, 46, 42.5, CHAT, "In every conversation",
    "All three conditions, identically.\n"
    "The agent starts from:\n"
    "  - its persona\n"
    "  - today's date\n"
    "  - all dated summaries of earlier\n"
    "    conversations")
box(54, 19, 96, 42.5, NOTIFY, "In the Affective notification",
    "Written by the language model from:\n"
    "  1. the best unused event\n"
    "      (highest score, then most recent;\n"
    "      used once; never expires)\n"
    "  2. else the 5 most recent summaries\n"
    "  3. else a fixed warm message")

arrow((50, 90.5), (50, 85.5))
arrow((36, 70), (25, 63.5))
arrow((64, 70), (75, 63.5))
arrow((25, 49.5), (25, 42.5))
arrow((75, 49.5), (75, 42.5))
arrow((46, 51.5), (54, 30.2), dashed=True)   # the summaries feed step 2 of the notification
arrow((54, 22.5), (46, 22.5), dashed=True)   # an event notification adds that event to its conversation
ax.text(50, 16.6, "a conversation opened from a notification about an event\n"
                  "is also given that event and an excerpt of where it was shared",
        ha="center", va="center", fontsize=7.6, color=MUTED, style="italic", linespacing=1.3)

# 5. the three conditions
ax.plot([4, 96], [12.2, 12.2], color="#c9c8c2", linewidth=0.8)
ax.text(4, 10.2, "What each condition sends", ha="left", va="center", fontsize=8.6, fontweight="bold", color=INK)
for x0, x1, name, text in ((4, 32.5, "Reactive", "no notifications"),
                           (35.75, 64.25, "Standard Proactive", "neutral message from a fixed\npool; no memory, no name"),
                           (67.5, 96, "Affective Proactive", "memory-based message\n(right-hand box above)")):
    ax.add_patch(FancyBboxPatch((x0, 0.8), x1 - x0, 7.4, boxstyle="round,pad=0,rounding_size=1.0",
                                facecolor="white", edgecolor=MUTED, linewidth=1.0))
    ax.text((x0 + x1) / 2, 7.2, name, ha="center", va="top", fontsize=8.4, fontweight="bold", color=INK)
    ax.text((x0 + x1) / 2, 4.9, text, ha="center", va="top", fontsize=7.6, color=INK, linespacing=1.25)

here = os.path.dirname(os.path.abspath(__file__))
for ext, extra in (("pdf", {}), ("svg", {}), ("png", {"dpi": 220})):
    fig.savefig(os.path.join(here, f"memory_design.{ext}"), bbox_inches="tight", pad_inches=0.08, **extra)
print("written: memory_design.pdf, .svg, .png in", here)
