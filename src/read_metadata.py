"""第3个程序：用 pandas 读电池档案表 metadata.csv"""
import pandas as pd

df = pd.read_csv(r"C:\Users\22011\Desktop\26暑假\ai_scientist\data\metadata.csv")

print("===== 前 5 行 =====")
print(df.head())

print("===== 形状（行数, 列数）=====")
print(df.shape)

print("===== 每个实验组有几块电池 =====")
print(df["group"].value_counts())

print("===== 每列数据类型 =====")
print(df.dtypes)

print("===== 每列缺失值数量 =====")
print(df.isna().sum())