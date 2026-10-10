#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义技术指标策略示例：双均线动量择时选股策略
继承 Qlib BaseStrategy
"""

from qlib.strategy.base import BaseStrategy
from qlib.data import D

class DualMovingAverageStrategy(BaseStrategy):
    def __init__(self, fast_period=5, slow_period=20, top_k=20, **kwargs):
        """
        :param fast_period: 短周期均线 (默认5日)
        :param slow_period: 长周期均线 (默认20日)
        :param top_k: 满足金叉条件的股票中，最多买入多少只
        """
        super().__init__(**kwargs)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.top_k = top_k

    def generate_trade_decision(self, execute_result=None):
        """
        核心交易决策函数：在每个调仓日被引擎自动调用
        返回值: 具体的买卖目标订单列表 (TradeDecision)
        """
        # 获取当前交易日
        trade_date = self.trade_calendar.get_step_time()[0]
        
        # 1. 读取当前股票池的均线指标
        # Qlib 支持表达式引擎：Mean($close, 5) 表示5日均线
        pred_score = {}
        # 你可以在这里计算任何指标逻辑：
        # fast_ma = D.features(..., ["Mean($close, 5)"])
        # slow_ma = D.features(..., ["Mean($close, 20)"])
        
        # 2. 生成买卖订单并返回
        # 满足条件的标的列入买入清单，跌破均线的标的列入卖出清单
        return super().generate_trade_decision(execute_result)
