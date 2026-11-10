"""第5个程序：统计操作类型 + 提取每次放电的容量 + 画衰减曲线"""
from scipy.io import loadmat
from collections import Counter
import numpy as np
import matplotlib.pyplot as plt

# 让 matplotlib 使用系统中文字体（否则中文会显示成方块）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
plt.rcParams["axes.unicode_minus"] = False


def scalar(x):
    """把 scipy 读出来的嵌套数组剥到底，转成 Python 数字"""
    x = np.asarray(x)
    while hasattr(x, "size") and x.size == 1:
        x = x.item()
    return float(x)


mat = loadmat(r"C:\Users\22011\Desktop\26暑假\ai_scientist\data\Battery_DataSet\Battery_DataSet\B0005.mat")
cell = mat["B0005"][0, 0]
cycles = cell["cycle"][0]

# 1) 统计三种操作各有多少次
type_counter = Counter()
for c in cycles:
    t = str(c["type"][0])
    type_counter[t] += 1
print("操作类型统计:", dict(type_counter))

# 2) 遍历所有循环，把每次放电的容量收集起来
capacities = []
for c in cycles:
    t = str(c["type"][0])
    if t == "discharge":
        cap = scalar(c["data"]["Capacity"])
        capacities.append(cap)

print("放电次数:", len(capacities))
print("前 5 次容量:", [round(x, 3) for x in capacities[:5]])
print("后 5 次容量:", [round(x, 3) for x in capacities[-5:]])
print("容量在下降吗？", capacities[0] > capacities[-1])

# 3) 画容量衰减曲线
cycle_numbers = list(range(1, len(capacities) + 1))
plt.plot(cycle_numbers, capacities, marker="o", markersize=2, linewidth=1)
plt.xlabel("放电循环编号")
plt.ylabel("容量 (Ahr)")
plt.title("B0005 电池容量衰减曲线")
plt.grid(True)
plt.savefig(r"C:\Users\22011\Desktop\26暑假\ai_scientist\data\capacity_B0005.png", dpi=150)
print("图片已保存：data/capacity_B0005.png")