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
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "legend.fontsize": 10.5,
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

os.makedirs("figures", exist_ok=True)
os.makedirs("docs/figures", exist_ok=True)

def save_fig(fig, base_name):
    p1 = f"figures/{base_name}.png"
    p2 = f"docs/figures/{base_name}.png"
    fig.savefig(p1, dpi=300, bbox_inches="tight")
    fig.savefig(p2, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {p1} and {p2}")

# =============================================================
# 1. BIỂU ĐỒ 2.4A: Linear Scale (Extreme Right Skewness)
# =============================================================
print("Generating Figure 2.4a...")
fig1, ax1 = plt.subplots(figsize=(9, 6.2))

bins_linear = np.linspace(0, 365, 73)  # 5-day bins
counts, edges = np.histogram(arr, bins=bins_linear, density=True)
bin_centers = (edges[:-1] + edges[1:]) / 2

ax1.bar(bin_centers, counts, width=4.5, color="#3498db", alpha=0.6, edgecolor="#2980b9", label="Mật độ thực tế (Histogram)")
ax1.axvline(median_val, color="#c0392b", linestyle="--", linewidth=2.5, label=f"Trung vị (Median p50) = {median_val:.2f} ngày")
ax1.axvline(mean_val, color="#8e44ad", linestyle="-.", linewidth=2.5, label=f"Trung bình (Mean) = {mean_val:.2f} ngày (bách phân vị p{pct_mean:.1f})")
ax1.axvspan(0, median_val, color="#e74c3c", alpha=0.15, label="50% công việc giải quyết trong ≤ 11 ngày")

ax1.annotate(
    f"Mean gấp {mean_val/median_val:.2f} lần Median\n(Δ = {mean_val - median_val:.1f} ngày)",
    xy=(mean_val, counts.max() * 0.40),
    xytext=(mean_val + 35, counts.max() * 0.62),
    arrowprops=dict(facecolor="#8e44ad", arrowstyle="->", lw=1.8),
    bbox=dict(boxstyle="round,pad=0.5", facecolor="#f4ecf7", edgecolor="#8e44ad", lw=1.3),
    fontsize=10.5, fontweight="bold"
)

ax1.set_xlim(0, 365)
ax1.set_xlabel("Thời gian chu kỳ giải quyết (Ngày - Thang Tuyến tính)")
ax1.set_ylabel("Mật độ xác suất (Probability Density)")
ax1.set_title("Hình 2.4a: Phân Phối Chu Kỳ Giải Quyết Nhiệm Vụ Trên Thang Tuyến Tính\n(Minh Họa Hiện Tượng Lệch Phải Cực Hạn & Khoảng Cách Mean vs Median)", fontweight="bold")
ax1.legend(loc="upper right", frameon=True, fontsize=10)
ax1.grid(True, linestyle=":", alpha=0.6)

ax1.text(
    0.98, 0.25,
    f"• Quy mô mẫu: N = {n:,} issues\n"
    f"• 20.25% nhiệm vụ (> {mean_val:.1f} ngày) nằm ở đuôi dài\n"
    f"• Bách phân vị p90 = {p90:.1f} ngày (~1.8 năm)\n"
    f"• Bách phân vị p99 = {p99:,.0f} ngày (~6.9 năm)\n"
    f"• Độ lệch (Skewness) = +{skew_val:.2f}\n"
    f"• Độ nhọn (Kurtosis) = {kurt_val:.1f}",
    transform=ax1.transAxes, ha="right", va="bottom",
    bbox=dict(boxstyle="round,pad=0.5", facecolor="#fff9e6", edgecolor="#f39c12", lw=1.1),
    fontsize=9.5
)

save_fig(fig1, "hinh_2_4a_cycle_time_linear_skew")

# =============================================================
# 2. BIỂU ĐỒ 2.4B: Log-Transformed Distribution (Log-Normal Fit)
# =============================================================
print("Generating Figure 2.4b...")
fig2, ax2 = plt.subplots(figsize=(9, 6.2))

log_days = np.log10(np.maximum(arr, 0.0001))
mu_log, std_log = np.mean(log_days), np.std(log_days)

bins_log = np.linspace(-4, 4.5, 86)
counts_log, edges_log = np.histogram(log_days, bins=bins_log, density=True)
bin_centers_log = (edges_log[:-1] + edges_log[1:]) / 2

ax2.bar(bin_centers_log, counts_log, width=0.08, color="#1abc9c", alpha=0.55, edgecolor="#16a085", label="Phân bố thực tế (Log-scale Histogram)")

x_log = np.linspace(-4, 4.5, 300)
pdf_log = stats.norm.pdf(x_log, mu_log, std_log)
ax2.plot(x_log, pdf_log, color="#d35400", linewidth=2.5, linestyle="-", label=f"Mô hình Log-Normal fit lý thuyết (μ={mu_log:.2f}, σ={std_log:.2f})")

milestones = [
    (np.log10(1/24), "1 Giờ", "#7f8c8d"),
    (np.log10(1), "1 Ngày", "#7f8c8d"),
    (np.log10(median_val), f"Median\n({median_val:.1f}d)", "#c0392b"),
    (np.log10(mean_val), f"Mean\n({mean_val:.1f}d)", "#8e44ad"),
    (np.log10(365), "1 Năm", "#7f8c8d"),
    (np.log10(p99), f"p99\n(~6.9y)", "#e74c3c"),
]
for x_val, label, col in milestones:
    ax2.axvline(x_val, color=col, linestyle=":", alpha=0.8, linewidth=1.4)
    ax2.text(x_val, counts_log.max() * 0.90, label, rotation=90, va="top", ha="right" if "Median" in label else "left", color=col, fontweight="bold", fontsize=9)

ax2.set_xlabel(r"$\log_{10}(\text{Cycle Time tính theo Ngày})$")
ax2.set_ylabel("Mật độ xác suất Logarit")
ax2.set_title("Hình 2.4b: Phân Phối Chu Kỳ Trên Thang Logarit & Tiệm Cận Log-Normal\n(Phản Ánh Quy Luật Nhân Tính Của Quá Trình Phát Triển Phần Mềm)", fontweight="bold")
ax2.legend(loc="upper left", frameon=True, fontsize=10)
ax2.grid(True, linestyle=":", alpha=0.6)

log_ticks = [-3, -2, -1, 0, 1, 2, 3, 4]
log_labels = ["~1.5 phút\n(0.001d)", "15 phút\n(0.01d)", "2.4 giờ\n(0.1d)", "1 ngày\n(1d)", "10 ngày\n(10d)", "100 ngày\n(100d)", "2.7 năm\n(1,000d)", "27 năm\n(10,000d)"]
ax2.set_xticks(log_ticks)
ax2.set_xticklabels(log_labels, fontsize=8.8)

save_fig(fig2, "hinh_2_4b_cycle_time_log_normal")

# =============================================================
# 3. BIỂU ĐỒ 2.4C: CCDF trên Thang Log-Log (Bằng chứng Pareto)
# =============================================================
print("Generating Figure 2.4c...")
fig3, ax3 = plt.subplots(figsize=(9, 6.2))

sorted_days = np.sort(arr)
eval_quantiles = np.linspace(0.001, 0.9999, 4000)
eval_days = np.percentile(sorted_days, eval_quantiles * 100)
ccdf_vals = 1.0 - eval_quantiles

pos_mask = eval_days > 0.01
x_ccdf = eval_days[pos_mask]
y_ccdf = ccdf_vals[pos_mask]

ax3.loglog(x_ccdf, y_ccdf, color="#2980b9", linewidth=2.5, label=r"Hàm sống thực tế $P(T > t)$ (Empirical CCDF)")

# Exponential reference
y_exp = np.exp(-x_ccdf / mean_val)
ax3.loglog(x_ccdf, y_exp, color="#e74c3c", linestyle="--", linewidth=1.8, label=f"Phân phối hàm mũ (Exponential, đuôi nhẹ μ={mean_val:.0f}d)")

# Pareto tail fit (for t > 100 days)
tail_mask = x_ccdf >= 100
slope, intercept, r_val, _, _ = stats.linregress(np.log10(x_ccdf[tail_mask]), np.log10(y_ccdf[tail_mask]))
pareto_fit_x = np.linspace(100, 10000, 100)
pareto_fit_y = 10**(intercept + slope * np.log10(pareto_fit_x))
ax3.loglog(pareto_fit_x, pareto_fit_y, color="#27ae60", linestyle="-.", linewidth=2.4, label=f"Tiệm cận Pareto đuôi nặng ($P(T > t) \\propto t^{{{slope:.2f}}}$, $R^2={r_val**2:.3f}$)")

ax3.axvline(median_val, color="#c0392b", linestyle=":", linewidth=1.4)
ax3.text(median_val * 1.15, 0.45, f"Median ({median_val:.1f}d)\nCCDF = 0.50", color="#c0392b", fontsize=9.5, fontweight="bold")

ax3.axvline(mean_val, color="#8e44ad", linestyle=":", linewidth=1.4)
ax3.text(mean_val * 1.15, 1 - pct_mean/100, f"Mean ({mean_val:.1f}d)\nCCDF = {1-pct_mean/100:.2f}", color="#8e44ad", fontsize=9.5, fontweight="bold")

ax3.set_xlabel("Thời gian chu kỳ t (Ngày - Thang Logarit)")
ax3.set_ylabel(r"Xác suất nhiệm vụ còn mở $P(T > t)$ (Thang Logarit)")
ax3.set_title("Hình 2.4c: Phân Phối Bù Tích Lũy (CCDF) Trên Thang Log-Log\n(Bằng Chứng Thực Nghiệm Tiệm Cận Suy Rộng Pareto / Đuôi Nặng)", fontweight="bold")
ax3.legend(loc="lower left", frameon=True, fontsize=9.5)
ax3.grid(True, which="both", linestyle=":", alpha=0.5)

save_fig(fig3, "hinh_2_4c_cycle_time_ccdf_pareto")

# =============================================================
# 4. BIỂU ĐỒ 2.4D: Percentiles Spectrum & Summary Card
# =============================================================
print("Generating Figure 2.4d...")
fig4, ax4 = plt.subplots(figsize=(9.5, 6.5))
ax4.axis("off")

ax4.text(0.02, 0.94, "Hình 2.4d: Phổ Bách Phân Vị & Thẻ Thống Kê Toán Học Vòng Đời Nhiệm Vụ", fontsize=13, fontweight="bold", transform=ax4.transAxes)

rect_y = 0.74
pct_labels = [
    ("p10\n40m", p10, 0.05, "#34495e"),
    ("p25\n15h", p25, 0.18, "#2980b9"),
    ("p50 (Median)\n10.95d", p50, 0.40, "#c0392b"),
    ("Mean\n206.65d", mean_val, 0.65, "#8e44ad"),
    ("p90\n1.8 năm", p90, 0.82, "#d35400"),
    ("p99\n6.9 năm", p99, 0.95, "#7f8c8d"),
]

ax4.plot([0.05, 0.95], [rect_y, rect_y], color="#bdc3c7", lw=5, zorder=1, transform=ax4.transAxes)
for lbl, val, x_pos, col in pct_labels:
    marker_size = 13 if "Median" in lbl or "Mean" in lbl else 9
    ax4.scatter(x_pos, rect_y, s=marker_size**2, color=col, zorder=3, transform=ax4.transAxes)
    ax4.text(x_pos, rect_y + 0.05, lbl, ha="center", va="bottom", color=col, fontweight="bold", fontsize=9.2, transform=ax4.transAxes)

ax4.text(0.5, rect_y - 0.06, "Thang bách phân vị phi tuyến (Percentiles Spectrum Timeline)", ha="center", va="top", fontsize=8.8, color="#7f8c8d", style="italic", transform=ax4.transAxes)

box_content = (
    "═════════════════════════════════════════════════════════════════════\n"
    " BẢNG THỐNG KÊ TOÁN HỌC ĐẶC TÍNH CHU KỲ (N = 2,308,108 ISSUES)\n"
    "═════════════════════════════════════════════════════════════════════\n"
    f" • Giá trị Trung vị (Median p50):           10.95 ngày\n"
    f" • Giá trị Trung bình (Mean):               206.65 ngày\n"
    f" • Tỷ số Mean / Median:                    18.87 lần  (Bất đối xứng cực hạn)\n"
    f" • Vị trí bách phân vị của Mean:           p79.75     (Gần 80% task xong trước Mean)\n"
    f" • Độ lệch chuẩn (Standard Deviation σ):     525.67 ngày\n"
    f" • Hệ số bất đối xứng (Skewness):          +6.46      (Lệch phải rất mạnh, Normal=0)\n"
    f" • Hệ số độ nhọn (Kurtosis):               109.15     (Đuôi cực dày, Normal=0)\n"
    "─────────────────────────────────────────────────────────────────────\n"
    f" • Bách phân vị p10:  0.03 ngày (40.5 phút) |  p25:  0.61 ngày (14.7 giờ)\n"
    f" • Bách phân vị p75:  122.14 ngày (~4 tháng)|  p90:  648.62 ngày (~1.8 năm)\n"
    f" • Bách phân vị p95:  1,230.0 ngày (~3.4 năm)| p99:  2,528.3 ngày (~6.9 năm)\n"
    "═════════════════════════════════════════════════════════════════════\n"
    " HỆ QUẢ MÔ HÌNH HÓA (MACHINE LEARNING IMPLICATIONS):\n"
    " 1. Mô hình hồi quy tuyến tính (MSE) hoàn toàn thất bại do đuôi nặng cực đoan.\n"
    " 2. Bắt buộc áp dụng Log-Transform hoặc mô hình Sinh tồn AFT / Cox Breslow.\n"
    " 3. Cơ chế phân ngưỡng trễ hạn phải chuẩn hóa theo Percentile từng dự án.\n"
    "═════════════════════════════════════════════════════════════════════"
)

ax4.text(
    0.02, 0.53, box_content,
    family="monospace", fontsize=8.8, va="top",
    bbox=dict(boxstyle="round,pad=0.7", facecolor="#f8f9fa", edgecolor="#34495e", lw=1.3),
    transform=ax4.transAxes
)

save_fig(fig4, "hinh_2_4d_cycle_time_percentiles_summary")

print("All 4 figures generated successfully!")
