import duckdb
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy import stats
import os

# Set publication style
plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "xtick.labelsize": 9.5,
    "ytick.labelsize": 9.5,
    "legend.fontsize": 9.5,
    "figure.titlesize": 14,
    "figure.dpi": 300,
})

print("1. Pulling cycle time data from DuckDB...")
con = duckdb.connect("data/jira.duckdb", read_only=True)
q = "SELECT (resolved_ts - created_ts) / 86400.0 as days FROM issues WHERE resolved_ts IS NOT NULL AND resolved_ts >= created_ts"
arr = con.execute(q).fetchnumpy()['days']
n = len(arr)
print(f"Loaded {n:,} points.")

# Metrics
mean_val = float(np.mean(arr))
median_val = float(np.median(arr))
std_val = float(np.std(arr))
skew_val = float(stats.skew(arr))
kurt_val = float(stats.kurtosis(arr))
pct_mean = float(np.mean(arr <= mean_val) * 100.0)

p05 = float(np.percentile(arr, 5))
p10 = float(np.percentile(arr, 10))
p25 = float(np.percentile(arr, 25))
p50 = median_val
p75 = float(np.percentile(arr, 75))
p90 = float(np.percentile(arr, 90))
p95 = float(np.percentile(arr, 95))
p99 = float(np.percentile(arr, 99))
max_val = float(np.max(arr))

print(f"Mean: {mean_val:.2f}, Median: {median_val:.2f}, Ratio: {mean_val/median_val:.2f}x")
print(f"Mean is at percentile: {pct_mean:.2f}%")

# Create figure
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle(
    "Đặc Tính Phân Phối Chu Kỳ Giải Quyết Nhiệm Vụ (Cycle Time Distribution)\n"
    f"Toàn Bộ Kho Dữ Liệu Jira (N = {n:,} Issues Đã Giải Quyết — 16 Hệ Sinh Thái)",
    fontsize=14, fontweight="bold", y=0.98
)

# -------------------------------------------------------------
# Panel A: Linear Scale Density (Extreme Right Skewness)
# -------------------------------------------------------------
ax1 = axes[0, 0]
# Clip to 365 days for visible body, but show full extent
arr_clip = arr[arr <= 365]

bins_linear = np.linspace(0, 365, 73)  # 5-day bins
counts, edges = np.histogram(arr, bins=bins_linear, density=True)
bin_centers = (edges[:-1] + edges[1:]) / 2

# Plot bar
ax1.bar(bin_centers, counts, width=4.5, color="#3498db", alpha=0.6, edgecolor="#2980b9", label="Mật độ thực tế (Histogram)")

# Highlight median and mean
ax1.axvline(median_val, color="#c0392b", linestyle="--", linewidth=2.2, label=f"Trung vị (Median p50) = {median_val:.2f} ngày")
ax1.axvline(mean_val, color="#8e44ad", linestyle="-.", linewidth=2.2, label=f"Trung bình (Mean) = {mean_val:.2f} ngày (p{pct_mean:.1f})")

# Shading under median
ax1.axvspan(0, median_val, color="#e74c3c", alpha=0.15, label="50% công việc giải quyết trong 11 ngày")

# Annotation for 18.87x ratio
ax1.annotate(
    f"Mean gấp {mean_val/median_val:.2f} lần Median\n(Δ = {mean_val - median_val:.1f} ngày)",
    xy=(mean_val, counts.max() * 0.45),
    xytext=(mean_val + 30, counts.max() * 0.65),
    arrowprops=dict(facecolor="#8e44ad", arrowstyle="->", lw=1.5),
    bbox=dict(boxstyle="round,pad=0.4", facecolor="#f4ecf7", edgecolor="#8e44ad", lw=1.2),
    fontsize=9.5, fontweight="bold"
)

ax1.set_xlim(0, 365)
ax1.set_xlabel("Thời gian chu kỳ giải quyết (Ngày - Thang Tuyến tính)")
ax1.set_ylabel("Mật độ xác suất (Density)")
ax1.set_title("A. Phân Phối Trên Thang Tuyến Tính (Lệch Phải Cực Hạn)", fontweight="bold")
ax1.legend(loc="upper right", frameon=True, fontsize=8.5)
ax1.grid(True, linestyle=":", alpha=0.6)

# Add note about the long tail
ax1.text(
    0.98, 0.28,
    f"Lưu ý: 20.25% nhiệm vụ (> {mean_val:.1f} ngày)\n"
    f"nằm ở đuôi dài kéo tới {p99:,.0f} ngày (p99)\n"
    f"Độ lệch Skewness = +{skew_val:.2f}\n"
    f"Độ nhọn Kurtosis = {kurt_val:.1f}",
    transform=ax1.transAxes, ha="right", va="bottom",
    bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff9e6", edgecolor="#f39c12", lw=1.0),
    fontsize=8.5
)

# -------------------------------------------------------------
# Panel B: Log-Transformed Distribution (Log-Normal Fit)
# -------------------------------------------------------------
ax2 = axes[0, 1]
# Log10(days + 0.001) to handle 0 days
log_days = np.log10(np.maximum(arr, 0.0001))
mu_log, std_log = np.mean(log_days), np.std(log_days)

bins_log = np.linspace(-4, 4.5, 86)
counts_log, edges_log = np.histogram(log_days, bins=bins_log, density=True)
bin_centers_log = (edges_log[:-1] + edges_log[1:]) / 2

ax2.bar(bin_centers_log, counts_log, width=0.08, color="#1abc9c", alpha=0.55, edgecolor="#16a085", label="Phân bố thực tế (Log-scale)")

# Fit Log-Normal theoretical curve
x_log = np.linspace(-4, 4.5, 300)
pdf_log = stats.norm.pdf(x_log, mu_log, std_log)
ax2.plot(x_log, pdf_log, color="#d35400", linewidth=2.2, linestyle="-", label=f"Mô hình Log-Normal fit (μ={mu_log:.2f}, σ={std_log:.2f})")

# Marker lines for meaningful milestones
milestones = [
    (np.log10(1/24), "1 Giờ", "#7f8c8d"),
    (np.log10(1), "1 Ngày", "#7f8c8d"),
    (np.log10(median_val), f"Median\n({median_val:.1f}d)", "#c0392b"),
    (np.log10(mean_val), f"Mean\n({mean_val:.1f}d)", "#8e44ad"),
    (np.log10(365), "1 Năm", "#7f8c8d"),
    (np.log10(p99), f"p99\n(~7 năm)", "#e74c3c"),
]
for x_val, label, col in milestones:
    ax2.axvline(x_val, color=col, linestyle=":", alpha=0.75, linewidth=1.2)
    if "Median" in label or "Mean" in label or "p99" in label:
        ax2.text(x_val, counts_log.max() * 0.90, label, rotation=90, va="top", ha="right" if "Median" in label else "left", color=col, fontweight="bold", fontsize=8)

ax2.set_xlabel(r"$\log_{10}(\text{Cycle Time trong Ngày})$")
ax2.set_ylabel("Mật độ xác suất logarit")
ax2.set_title("B. Phân Phối Trên Thang Logarit & Khảo Sát Tiệm Cận Log-Normal", fontweight="bold")
ax2.legend(loc="upper left", frameon=True, fontsize=8.5)
ax2.grid(True, linestyle=":", alpha=0.6)

# Custom tick labels for log axis
log_ticks = [-3, -2, -1, 0, 1, 2, 3, 4]
log_labels = ["~1.5 phút\n(0.001d)", "15 phút\n(0.01d)", "2.4 giờ\n(0.1d)", "1 ngày\n(1d)", "10 ngày\n(10d)", "100 ngày\n(100d)", "2.7 năm\n(1,000d)", "27 năm\n(10,000d)"]
ax2.set_xticks(log_ticks)
ax2.set_xticklabels(log_labels, fontsize=8)

# -------------------------------------------------------------
# Panel C: CCDF (Log-Log Survival Function - Pareto Evidence)
# -------------------------------------------------------------
ax3 = axes[1, 0]
# Sort for empirical CCDF
sorted_days = np.sort(arr)
# Sample 5000 points evenly across quantiles for smooth, light plotting
eval_quantiles = np.linspace(0.001, 0.9999, 4000)
eval_days = np.percentile(sorted_days, eval_quantiles * 100)
ccdf_vals = 1.0 - eval_quantiles

# Mask positive days
pos_mask = eval_days > 0.01
x_ccdf = eval_days[pos_mask]
y_ccdf = ccdf_vals[pos_mask]

ax3.loglog(x_ccdf, y_ccdf, color="#2980b9", linewidth=2.2, label=r"Hàm sống thực tế $P(T > t)$ (Empirical CCDF)")

# Plot theoretical Exponential (light-tailed) comparison with same mean
y_exp = np.exp(-x_ccdf / mean_val)
ax3.loglog(x_ccdf, y_exp, color="#e74c3c", linestyle="--", linewidth=1.6, label=f"Phân phối hàm mũ (Exponential, đuôi nhẹ μ={mean_val:.0f}d)")

# Pareto tail fit (for t > 100 days)
tail_mask = x_ccdf >= 100
slope, intercept, r_val, _, _ = stats.linregress(np.log10(x_ccdf[tail_mask]), np.log10(y_ccdf[tail_mask]))
pareto_fit_x = np.linspace(100, 10000, 100)
pareto_fit_y = 10**(intercept + slope * np.log10(pareto_fit_x))
ax3.loglog(pareto_fit_x, pareto_fit_y, color="#27ae60", linestyle="-.", linewidth=2.0, label=f"Tiệm cận Pareto đuôi nặng ($P(T > t) \\propto t^{{{slope:.2f}}}$, $R^2={r_val**2:.3f}$)")

ax3.axvline(median_val, color="#c0392b", linestyle=":", linewidth=1.2)
ax3.text(median_val * 1.1, 0.5, f"Median ({median_val:.1f}d)\nCCDF=0.50", color="#c0392b", fontsize=8.5, fontweight="bold")

ax3.axvline(mean_val, color="#8e44ad", linestyle=":", linewidth=1.2)
ax3.text(mean_val * 1.1, 1 - pct_mean/100, f"Mean ({mean_val:.1f}d)\nCCDF={1-pct_mean/100:.2f}", color="#8e44ad", fontsize=8.5, fontweight="bold")

ax3.set_xlabel("Thời gian chu kỳ t (Ngày - Thang Logarit)")
ax3.set_ylabel(r"Xác suất còn mở $P(T > t)$ (Thang Logarit)")
ax3.set_title("C. Phân Phối Bù Tích Lũy (CCDF) Trên Thang Log-Log: Bằng Chứng Pareto", fontweight="bold")
ax3.legend(loc="lower left", frameon=True, fontsize=8.5)
ax3.grid(True, which="both", linestyle=":", alpha=0.5)

# -------------------------------------------------------------
# Panel D: Percentile Spectrum & Mathematical Summary Card
# -------------------------------------------------------------
ax4 = axes[1, 1]
ax4.axis("off")  # Draw structured visual table/cards

# Draw Percentiles Bar Diagram
rect_y = 0.72
bar_height = 0.08
ax4.text(0.02, 0.94, "D. Phổ Bách Phân Vị & Thẻ Thống Kê Toán Học Tóm Tắt", fontsize=12, fontweight="bold", transform=ax4.transAxes)

# Visual horizontal timeline bar
pct_labels = [
    ("p10\n40m", p10, 0.05, "#34495e"),
    ("p25\n15h", p25, 0.18, "#2980b9"),
    ("p50 (Median)\n10.95d", p50, 0.40, "#c0392b"),
    ("Mean\n206.65d", mean_val, 0.65, "#8e44ad"),
    ("p90\n1.8 năm", p90, 0.82, "#d35400"),
    ("p99\n6.9 năm", p99, 0.95, "#7f8c8d"),
]

# Draw horizontal line representing spectrum
ax4.plot([0.05, 0.95], [rect_y, rect_y], color="#bdc3c7", lw=4, zorder=1, transform=ax4.transAxes)
for lbl, val, x_pos, col in pct_labels:
    # dot
    marker_size = 12 if "Median" in lbl or "Mean" in lbl else 8
    ax4.scatter(x_pos, rect_y, s=marker_size**2, color=col, zorder=3, transform=ax4.transAxes)
    ax4.text(x_pos, rect_y + 0.05, lbl, ha="center", va="bottom", color=col, fontweight="bold", fontsize=8.5, transform=ax4.transAxes)

ax4.text(0.5, rect_y - 0.06, "Thang bách phân vị phi tuyến (Percentiles Spectrum)", ha="center", va="top", fontsize=8, color="#7f8c8d", style="italic", transform=ax4.transAxes)

# Stats Table Box
box_content = (
    "═══════════════════════════════════════════════════════════════\n"
    " BẢNG THỐNG KÊ TOÁN HỌC ĐẶC TÍNH CHU KỲ (N = 2,308,108)\n"
    "═══════════════════════════════════════════════════════════════\n"
    f" • Giá trị Trung vị (Median p50):           10.95 ngày\n"
    f" • Giá trị Trung bình (Mean):               206.65 ngày\n"
    f" • Tỷ số Mean / Median:                    18.87 lần  (Bất đối xứng cực hạn)\n"
    f" • Vị trí bách phân vị của Mean:           p79.75     (Gần 80% task xong trước Mean)\n"
    f" • Độ lệch chuẩn (Standard Deviation σ):     525.67 ngày\n"
    f" • Hệ số bất đối xứng (Skewness):          +6.46      (Lệch phải rất mạnh, Normal=0)\n"
    f" • Hệ số độ nhọn (Kurtosis):               109.15     (Đuôi cực dày, Normal=0)\n"
    "───────────────────────────────────────────────────────────────\n"
    f" • Bách phân vị p10:  0.03 ngày (40.5 phút) |  p25:  0.61 ngày (14.7 giờ)\n"
    f" • Bách phân vị p75:  122.14 ngày (~4 tháng)|  p90:  648.62 ngày (~1.8 năm)\n"
    f" • Bách phân vị p95:  1,230.0 ngày (~3.4 năm)| p99:  2,528.3 ngày (~6.9 năm)\n"
    "═══════════════════════════════════════════════════════════════\n"
    " HỆ QUẢ MÔ HÌNH HÓA (MACHINE LEARNING IMPLICATIONS):\n"
    " 1. Mô hình hồi quy tuyến tính (MSE) hoàn toàn thất bại do đuôi nặng.\n"
    " 2. Bắt buộc sử dụng hàm tổn thất Log-Transform hoặc AFT (Survival Analysis).\n"
    " 3. Cơ chế phân loại trễ hạn phải dùng ngưỡng theo Percentile từng dự án.\n"
    "═══════════════════════════════════════════════════════════════"
)

ax4.text(
    0.02, 0.52, box_content,
    family="monospace", fontsize=8.2, va="top",
    bbox=dict(boxstyle="round,pad=0.6", facecolor="#f8f9fa", edgecolor="#34495e", lw=1.2),
    transform=ax4.transAxes
)

plt.tight_layout(rect=[0, 0, 1, 0.95])

out_fig1 = "figures/hinh_2_4_cycle_time_heavy_tail.png"
out_fig2 = "docs/figures/hinh_2_4_cycle_time_heavy_tail.png"
os.makedirs("figures", exist_ok=True)
os.makedirs("docs/figures", exist_ok=True)

fig.savefig(out_fig1, dpi=300)
fig.savefig(out_fig2, dpi=300)
plt.close(fig)

print(f"Saved publication-quality figure to {out_fig1} and {out_fig2}")
