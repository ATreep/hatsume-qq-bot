import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC"]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["font.size"] = 12

import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties, fontManager
import os

# Register Noto Sans CJK SC font explicitly via font path
import subprocess
result = subprocess.run(["fc-list", "Noto Sans CJK SC", "file"], capture_output=True, text=True)
ttf_paths = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
print(f"Found TTF paths: {ttf_paths}")

for p in ttf_paths[:1]:
    if os.path.exists(p):
        fp = FontProperties(fname=p)
        print(f"Registered font: {fp.get_name()}, family={fp.get_family()}")
        break

# --- Plot ---
fig, ax = plt.subplots(figsize=(10, 6))

labels = ['老实复利算法', '江姐同款算法']
values = [170.6, 8500]
colors = ['#E87A5F', '#2EDB71']  # soft orange-red, bright green
subtexts = ['95分本金 × 1.05¹²', '一天95、两天190、\n三天285 → 3×10×285−50']

bars = ax.bar(labels, values, color=colors, width=0.45, edgecolor='white', linewidth=1.2, zorder=3)

# Log scale y-axis
ax.set_yscale('log')

# Add value labels on top of bars (using annotate for precise positioning)
for bar, val, sub in zip(bars, values, subtexts):
    height = bar.get_height()
    ax.annotate(f'{val:.1f}',
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 8), textcoords="offset points",
                ha='center', va='bottom', fontsize=11, fontweight='bold',
                color='#333333')
    # Subtext below bar
    ax.annotate(sub,
                xy=(bar.get_x() + bar.get_width() / 2, -height * 0.05),
                xytext=(0, -12), textcoords="offset points",
                ha='center', va='top', fontsize=8, color='#666666')

# Title & subtitle
ax.set_title('同一笔95分的夜宵账，换个算法直接起飞', fontsize=16, fontweight='bold', pad=18)
ax.text(0.5, -0.18,
        '折合烤串（3分一串）：老实版 57 串 vs 江姐版 2833 串\n本图纯属数学事故，不构成催款依据',
        transform=ax.transAxes, ha='center', va='top', fontsize=8.5,
        color='#777777', wrap=False)

# Y-axis label
ax.set_ylabel('单位：分', fontsize=11, labelpad=8)

# Y-ticks with log scale formatting
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.0f}' if x >= 1 else f'{x}'))

# Remove unnecessary spines
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['left'].set_visible(True)
ax.spines['bottom'].set_visible(True)
ax.spines['left'].set_color('#ccc')
ax.spines['bottom'].set_color('#ccc')

# Grid only horizontal (minor ticks for log scale)
ax.yaxis.set_minor_locator(plt.LogLocator(base=10.0, numticks=12))
ax.grid(axis='y', which='major', linestyle='--', alpha=0.3)
ax.grid(axis='y', which='minor', linestyle=':', alpha=0.15)
ax.set_axisbelow(True)

# X-axis tick style
ax.tick_params(axis='x', labelsize=11, length=0)
ax.tick_params(axis='y', labelsize=10, length=0, colors='#888')

# Adjust layout
fig.tight_layout()

# Save
out_path = '/work/hatsume/compare/jiangjie.png'
fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white', transparent=False)
plt.close(fig)
print(f"Saved to {out_path}")
