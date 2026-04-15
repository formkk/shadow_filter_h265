
import numpy as np
import os

# New I7-13700 / RTX3090 Data (From log file lines 7-17)
i7_data = [
    [49.22, 69.89, 103.30, 30.20],
    [49.22, 69.87, 103.30, 29.30],
    [49.31, 69.87, 103.30, 28.78],
    [49.24, 69.83, 103.30, 29.14],
    [49.28, 69.87, 103.30, 29.30],
    [49.21, 69.89, 103.30, 29.37],
    [49.27, 69.89, 103.30, 29.85],
    [49.43, 69.89, 103.30, 30.34],
    [49.44, 69.97, 103.30, 30.70],
    [49.42, 69.98, 103.30, 30.69],
    [49.39, 70.06, 103.30, 30.70]
]

# Hygon CPU / RTX3090 Data
hygon_data = [
    [80.43, 98.06, 104.72, 58.71],
    [80.46, 98.06, 104.72, 59.13],
    [80.44, 98.01, 104.72, 59.60],
    [80.53, 98.04, 104.72, 60.06],
    [80.48, 97.93, 104.72, 60.14],
    [80.51, 97.87, 104.88, 60.07],
    [80.44, 97.84, 104.88, 60.18],
    [80.45, 97.83, 104.88, 59.47],
    [80.53, 97.84, 104.88, 59.07],
    [80.63, 97.96, 104.88, 59.26]
]

# Columns: mean_ms, p95_ms, max_ms, avg_ai_ms

def calculate_stats(data):
    data_np = np.array(data)
    means = np.mean(data_np, axis=0)
    return means

i7_stats = calculate_stats(i7_data)
hygon_stats = calculate_stats(hygon_data)

# Calculate difference (Hygon - I7)
diff = hygon_stats - i7_stats
# Calculate relative difference ((Hygon - I7) / I7 * 100)
rel_diff = (hygon_stats - i7_stats) / i7_stats * 100

report_content = f"""# 异构平台性能对比报告：I7-13700 vs 海光 CPU (均搭载 RTX3090)

**生成时间**: 2026-03-03
**对比项目**: 管道延迟与AI推理性能 (不同CPU架构下的GPU系统表现)

## 1. 测试环境

*   **基准环境**: Intel Core i7-13700 + NVIDIA RTX3090 (数据源: 日志 L7-L17)
*   **对比环境**: 海光 CPU (Hygon) + NVIDIA RTX3090

## 2. 数据摘要 (单位: ms)

基于最近连续运行的性能日志数据进行平均值计算。

| 指标 | I7-13700 + 3090 | 海光 + 3090 | 差异 (ms) | 性能差异 (%) |
| :--- | :--- | :--- | :--- | :--- |
| **平均管道延迟 (Mean)** | {i7_stats[0]:.2f} | {hygon_stats[0]:.2f} | +{diff[0]:.2f} | +{rel_diff[0]:.2f}% (更慢) |
| **P95 延迟 (95th%)** | {i7_stats[1]:.2f} | {hygon_stats[1]:.2f} | +{diff[1]:.2f} | +{rel_diff[1]:.2f}% (更慢) |
| **最大延迟 (Max)** | {i7_stats[2]:.2f} | {hygon_stats[2]:.2f} | +{diff[2]:.2f} | +{rel_diff[2]:.2f}% (更慢) |
| **平均 AI 推理耗时** | {i7_stats[3]:.2f} | {hygon_stats[3]:.2f} | +{diff[3]:.2f} | +{rel_diff[3]:.2f}% (更慢) |

## 3. 详细分析

本次测试在**相同的 GPU (RTX3090)** 下对比了不同 CPU 对系统整体性能的影响。

### 3.1 瓶颈分析：CPU 对 GPU 性能的制约
*   **AI 推理耗时**: 海光平台的 AI 推理平均耗时 ({hygon_stats[3]:.2f} ms) 约为 I7 平台 ({i7_stats[3]:.2f} ms) 的 **2倍** (+{rel_diff[3]:.2f}%)。
    *   **原因推测**: 这通常不是 GPU 本身算力的问题，而是 **CPU 瓶颈** 导致的。可能的因素包括：
        1.  **数据预处理慢**: 图像缩放、归一化等操作在 CPU 上执行，拖慢了整体 pipeline。
        2.  **数据传输受限**: 海光平台的 PCIe 带宽利用率或内存带宽可能较低，导致数据上传到 GPU 的速度变慢。
        3.  **调度延迟**: CPU 单核性能较弱，导致 Python 解释器开销占比变大，无法及时向 GPU 发送 CUDA kernel 指令 (Kernel Launch Latency)。

### 3.2 管道延迟 (Pipeline Latency)
*   **平均延迟**: 受 AI 环节拖累，海光平台的整体管道延迟增加了 **{diff[0]:.2f} ms** (+{rel_diff[0]:.2f}%)。
*   **稳定性**: 在这组对比中，I7 平台的最大延迟 ({i7_stats[2]:.2f} ms) 略低于海光平台 ({hygon_stats[2]:.2f} ms)，两者最大延迟非常接近，说明海光平台在峰值延迟控制上表现尚可，没有出现失控的情况。

## 4. 结论

1.  **CPU 性能对 AI 系统至关重要**: 即使拥有强大的 GPU，较弱的 CPU (如本例中的海光) 也会成为显著的瓶颈，导致 GPU 性能无法发挥，推理延迟增加约 100%。
2.  **木桶效应**: 在“海光 + RTX3090”的组合中，CPU 是明显的短板。若要提升性能，无需升级 GPU，而应着重优化 CPU 端的代码（如使用 C++ 重写预处理、多线程优化）或更换更强的 CPU。
3.  **国产化适配建议**: 若必须使用国产 CPU，需预留更大的延迟预算 (Latency Budget)，或者将更多的预处理任务移交给 GPU (如使用 NVIDIA DALI 库) 以减轻 CPU 负担。
"""

output_path = "/home/jiangfeng/shadow_filter_h265/docs/performance_report_hygon_rtx3090.md"
os.makedirs(os.path.dirname(output_path), exist_ok=True)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(report_content)

print(f"Report generated at: {output_path}")
print(report_content)
