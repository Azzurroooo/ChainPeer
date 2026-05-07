"""
全球市值最高的前5家科技公司 — 市值柱状图
柱状颜色按最新交易日涨跌幅从红(跌)到绿(涨)渐变
数据日期: 2026-03-31 (最近一个完整交易日)
"""

import matplotlib
matplotlib.use('Agg')  # 非交互式后端，保存为图片
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.font_manager as fm
import numpy as np

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 数据来源: stockanalysis.com / Google Finance  (2026-03-31)
# ============================================================
companies = {
    "Apple":      {"market_cap_t": 3.73, "daily_change": +0.73},
    "Microsoft":  {"market_cap_t": 3.34, "daily_change": -0.49},
    "NVIDIA":     {"market_cap_t": 3.32, "daily_change": -0.99},
    "Alphabet":   {"market_cap_t": 2.37, "daily_change": +0.35},
    "Amazon":     {"market_cap_t": 2.36, "daily_change": +0.73},
}

# 按市值降序排列
sorted_items = sorted(companies.items(), key=lambda x: x[1]["market_cap_t"], reverse=True)

names       = [item[0] for item in sorted_items]
market_caps = [item[1]["market_cap_t"] for item in sorted_items]
changes     = [item[1]["daily_change"] for item in sorted_items]

# ============================================================
# 颜色映射: 涨跌幅 → 红(跌) → 绿(涨) 渐变
#   涨跌幅范围: min_change(最红) ... max_change(最绿)
#   使用自定义的 红色 → 灰色 → 绿色 色谱
# ============================================================
min_change = min(changes)
max_change = max(changes)

def change_to_color(val, vmin, vmax):
    """
    将涨跌幅线性映射到 [红, 深灰, 绿] 渐变色。
    vmin → 纯红 (1,0,0)
    0    → 深灰 (0.35,0.35,0.35)  (平盘)
    vmax → 纯绿 (0,0.8,0)
    """
    if vmax == vmin:
        return (0.35, 0.35, 0.35)

    # 归一化到 [-1, 1] 范围
    if vmax > 0 and vmin < 0:
        norm = (val - vmin) / (vmax - vmin)   # 0..1
    elif vmax == 0:
        norm = 0.0
    else:
        # 全部为正或全部为负
        norm = (val - vmin) / (vmax - vmin)

    # 红色端点 (1, 0, 0), 中间灰 (0.35, 0.35, 0.35), 绿色端点 (0, 0.8, 0)
    # 分成两段: [0, 0.5] 红→灰, [0.5, 1] 灰→绿
    if norm <= 0.5:
        t = norm / 0.5  # 0..1
        r = 1.0 * (1 - t) + 0.35 * t
        g = 0.0 * (1 - t) + 0.35 * t
        b = 0.0 * (1 - t) + 0.35 * t
    else:
        t = (norm - 0.5) / 0.5  # 0..1
        r = 0.35 * (1 - t) + 0.0 * t
        g = 0.35 * (1 - t) + 0.80 * t
        b = 0.35 * (1 - t) + 0.0 * t

    return (r, g, b)

bar_colors = [change_to_color(c, min_change, max_change) for c in changes]

# ============================================================
# 绘图
# ============================================================
fig, ax = plt.subplots(figsize=(12, 7))

bars = ax.bar(names, market_caps, color=bar_colors, width=0.6, edgecolor='#333333', linewidth=0.8)

# 在柱子上方显示市值和涨跌幅
for bar, cap, chg in zip(bars, market_caps, changes):
    sign = "+" if chg >= 0 else ""
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
            f"${cap:.2f}T\n({sign}{chg:.2f}%)",
            ha='center', va='bottom', fontsize=12, fontweight='bold',
            color='#222222')

ax.set_ylabel("市值 (万亿美元 / Trillion USD)", fontsize=14, fontweight='bold', labelpad=10)
ax.set_title("全球市值最高的 5 家科技公司\n(柱状颜色 = 最近交易日涨跌幅: 红[跌] → 绿[涨])",
             fontsize=16, fontweight='bold', pad=20)

ax.set_ylim(0, max(market_caps) * 1.25)
ax.tick_params(axis='x', labelsize=13)
ax.tick_params(axis='y', labelsize=11)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.yaxis.grid(True, linestyle='--', alpha=0.4)

# 底部注释
ax.text(0.99, -0.12,
        "数据来源: stockanalysis.com / Google Finance  |  日期: 2026-03-31 (最近完整交易日)",
        transform=ax.transAxes, ha='right', va='top', fontsize=9, color='gray', style='italic')

# 添加颜色图例说明
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor=change_to_color(min_change, min_change, max_change),
          edgecolor='#333', label=f'跌幅最大 ({min_change:+.2f}%)'),
    Patch(facecolor=(0.35, 0.35, 0.35),
          edgecolor='#333', label='平盘 (0.00%)'),
    Patch(facecolor=change_to_color(max_change, min_change, max_change),
          edgecolor='#333', label=f'涨幅最大 ({max_change:+.2f}%)'),
]
ax.legend(handles=legend_elements, loc='upper right', fontsize=10,
          framealpha=0.9, edgecolor='#cccccc')

plt.tight_layout()

# 保存图片
output_path = "tech_market_cap_chart.png"
fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
print(f"[OK] Chart saved to: {output_path}")

# 也尝试显示
try:
    plt.show()
except Exception:
    print("(无法弹出窗口，请查看保存的图片文件)")
