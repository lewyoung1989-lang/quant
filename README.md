# A股量化研究与模拟回测系统 (基于微软 Qlib)

本项目基于微软开源的 AI 量化投资平台 [Microsoft Qlib](https://github.com/microsoft/qlib) 搭建，专为 **A 股市场** 量化策略研发、多因子特征工程、机器学习模型训练与精细化模拟回测而设计。

系统内建 A 股交易特性支持：
- **交易规则**：T+1 机制、涨跌停板（$\pm 10\%$ / $\pm 20\%$）撮合成交限制
- **交易费率**：支持买入佣金（如万2.5）、卖出佣金 + 印花税（千0.5）、5 元起收门槛与滑点设置
- **多因子库**：原生支持 Alpha158、Alpha360 经典技术因子，支持自定义表达式因子
- **回测基准**：对标沪深300（CSI300）、中证500（CSI500）等常用指数，自动计算超额收益（Alpha）与信息比率

---

## 目录结构

```text
quant/
├── .venv/                         # Python 虚拟环境 (配置好 Qlib + LightGBM + 科学计算依赖)
├── data/
│   └── cn_data/                   # 本地 A 股二进制日线行情数据集 (calendars, features, instruments)
├── configs/
│   └── workflow_config_lgbm_alpha158.yaml  # Qlib 声明式量化工作流配置
├── scripts/
│   ├── download_data.py           # 数据下载与更新脚本
│   ├── check_data.py              # 数据读取与验证脚本
│   └── visualize_results.py       # 净值曲线与动态回撤可视化工具
├── reports/                       # 回测报告、每日明细 CSV 与图表输出目录
├── run_quant_pipeline.py          # 端到端量化回测执行入口 (特征工程 -> 训练 -> 模拟撮合 -> 绩效评估)
└── README.md                      # 项目说明文档
```

---

## 快速开始

### 1. 激活虚拟环境
```bash
source .venv/bin/activate
```

### 2. 检查或更新 A 股数据
系统已配置好沪深300样本数据，如需更新或下载全市场数据：
```bash
# 下载简单测试数据
python scripts/download_data.py qlib_data_simple

# 或下载全量 A 股数据 (约 1GB)
python scripts/download_data.py qlib_data
```

### 3. 启动交互式 Web 投研控制台 (推荐)
```bash
streamlit run app.py
```
启动后在浏览器打开 **`http://localhost:8501`**，即可直接在页面上调整股票池、参数、并查看交互式走势与回测结果。

### 4. 命令行一键运行量化研发与模拟回测
```bash
python run_quant_pipeline.py
```
该流程将自动执行：
1. **数据切分与特征提取**：计算股票池各标的的 Alpha158 因子矩阵。
2. **AI 模型训练**：使用 LightGBM 回归模型学习因子的预测能力。
3. **选股信号生成**：给出每日股票评分，选取评分最高的 Top-30 股票。
4. **模拟撮合回测**：模拟每日开盘/收盘交易，扣除印花税与佣金，限制涨停买入与跌停卖出。
5. **绩效指标输出**：自动计算年化收益、基准收益、超额收益、最大回撤、夏普比率。

### 4. 生成可视化图表
回测完成后，运行以下命令生成净值曲线与回撤走势图：
```bash
python scripts/visualize_results.py
```
图表将保存于 `reports/cumulative_return.png`。

---

## 核心策略与回测参数调节

在 `run_quant_pipeline.py` 中可直接修改以下参数：

| 参数项 | 默认值 | 作用说明 |
| :--- | :--- | :--- |
| `market` | `"csi300"` | 股票池：可选 `"csi300"`, `"csi500"`, `"all"` |
| `benchmark` | `"SH000300"` | 对比基准指数（如沪深300） |
| `train_start` ~ `train_end` | `2017-01-01` ~ `2019-12-31` | 模型训练周期 |
| `test_start` ~ `test_end` | `2020-07-01` ~ `2020-12-31` | 模拟回测区间 |
| `top_k` | `30` | 每日目标持仓股票数量 |
| `n_drop` | `5` | 每日轮换淘汰股票数量 |
| `open_cost` | `0.00025` | 买入佣金（万分之 2.5） |
| `close_cost` | `0.00075` | 卖出佣金（万2.5） + 印花税（千0.5） |
| `account_cash` | `1000000` | 模拟初始资金（100 万元） |


## 模拟账户工作区（2026-10-17 接入）

启动 `streamlit run app.py`，选择「模拟账户」。可新增账户、自选攻守轮动或红利低波 ERP、设置初始资金、出入金、调整策略、查看委托清单、执行及导出流水。新账户默认手动，可开启尾盘自动模拟调仓；研究与回测入口继续保留。

手动和自动均在交易日 14:45–14:55 执行，并校验行情时效、前一交易日历史指标、现金与可卖份额。当前是参考价模拟整批成交，费用可配置，不模拟滑点、部分成交或真实券商订单。净投入比例用于收益率展示，不是专业时间加权业绩。

账户数据使用 `data/user_profile/simulation.sqlite3`，首次导入原 JSON，原文件保留。后续以 SQLite 为准；备份应停止应用和自动进程后复制整个账户目录。开启自动后由独立本地进程检查，电脑须保持运行；重启后需重新打开工作区或运行：

```bash
.venv/bin/python scripts/run_simulation_worker.py
# 只检查一次
.venv/bin/python scripts/run_simulation_worker.py --once
# 独立测试，不访问用户账户
.venv/bin/python -m unittest discover -s tests -v
```

当前提供 2026 年交易所日历；其他年份须按官方公告补充 `configs/trading_calendar_YYYY.json`，缺失时禁止执行。当前页面直接复用已确认 Demo 的前端，见[界面还原说明](docs/产物/模拟账户交互/版本_20261017/界面还原说明.md)。详细迁移、自动进程、参数与验证边界见[正式接入说明](docs/产物/模拟账户交互/版本_20261017/正式接入说明.md)，产物见[归档索引](docs/产物/README.md)。本次完成本地接入，未远程部署。
