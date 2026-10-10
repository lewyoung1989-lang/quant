#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义 A 股量化因子库
利用 Qlib 表达式引擎，免循环高性能计算海量因子
"""

# 常见 Qlib 内置算子：
# Mean($close, N)         : N日均线
# Std($close, N)          : N日波动率
# Ref($close, N)          : 往前推 N 日的值 (前收盘价)
# Delta($close, N)        : $close - Ref($close, N) (N日价差)
# Slope($close, N)        : N日回归斜率 (动量)
# Corr($close, $volume, N): N日价量相关系数

CUSTOM_FACTORS = {
    # 1. 动量类因子：20日收益动量
    "Momentum_20": "($close - Ref($close, 20)) / Ref($close, 20)",
    
    # 2. 均线突破类：当前价格偏离 60 日均线的幅度 (乖离率 BIAS)
    "BIAS_60": "($close - Mean($close, 60)) / Mean($close, 60)",
    
    # 3. 波动率类因子：最近 10 日收益率标准差
    "Volatility_10": "Std(($close - Ref($close, 1)) / Ref($close, 1), 10)",
    
    # 4. 价量因子：最近 20 日价量相关系数
    "Price_Volume_Corr_20": "Corr($close, $volume, 20)",
    
    # 5. 反转类因子：5日跌幅最大优先反转
    "Reversal_5": "-1 * ($close - Ref($close, 5)) / Ref($close, 5)"
}
