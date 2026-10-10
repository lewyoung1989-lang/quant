import os
import qlib
from qlib.data import D

# 初始化 Qlib，指向本地工作区数据
provider_uri = os.path.abspath("./data/cn_data")
print(f"[*] 初始化 Qlib 数据源: {provider_uri}")
qlib.init(provider_uri=provider_uri, region="cn")

# 1. 查询股票池
instruments = D.instruments(market="csi300")
stock_list = D.list_instruments(instruments=instruments, as_list=True)
print(f"[✓] CSI300 标的数量: {len(stock_list)}")
print(f"[*] 前 5 只股票代码: {stock_list[:5]}")

# 2. 提取行情特征测试
sample_stock = stock_list[0]
df = D.features(
    [sample_stock],
    fields=["$open", "$high", "$low", "$close", "$volume", "$factor"],
    start_time="2020-01-01",
    end_time="2020-01-15"
)
print(f"\n[✓] 股票 {sample_stock} 行情数据获取成功:")
print(df)
