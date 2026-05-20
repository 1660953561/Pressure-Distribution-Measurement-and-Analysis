import os
import pandas as pd

# ===============================
# 1. 文件路径
# ===============================
input_excel = r"D:\study\基于面压力分布在位测量的CMP加工机理研究\传感器数据\ 3kg5转\可使用分析数据\zhengti0.2.xlsx"

output_excel = os.path.join(
    os.path.dirname(input_excel),
    "zhengtifenlei0.2.xlsx"
)

# ===============================
# 2. 读取 Excel
# ===============================
df = pd.read_excel(input_excel)

# 简单校验
required_cols = {"Group_ID", "Row", "Col", "Pressure"}
if not required_cols.issubset(df.columns):
    raise ValueError("Excel 文件列名不正确")

# ===============================
# 3. 按坐标分组 + Group_ID 正序排列
# ===============================
df_sorted = (
    df
    .sort_values(by=["Row", "Col", "Group_ID"], ascending=[True, True, True])
    .reset_index(drop=True)
)

# ===============================
# 4. 保存为 Excel
# ===============================
df_sorted.to_excel(output_excel, index=False)

print("✅ 排序完成")
print(f"结果已保存到：\n{output_excel}")
print(f"总行数：{len(df_sorted)}")
