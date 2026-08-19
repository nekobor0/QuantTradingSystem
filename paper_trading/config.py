"""模拟仓配置。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = BASE_DIR / "state.json"

# 本金与分仓
PRINCIPAL = 1_000_000
DIV_WEIGHT = 0.75
VOL_WEIGHT = 0.25
DIV_CAPITAL = PRINCIPAL * DIV_WEIGHT   # 75 万
VOL_CAPITAL = PRINCIPAL * VOL_WEIGHT   # 25 万

# 股息分仓
YIELD_THRESHOLD = 0.05
TOP_N = 100

# 波动率+趋势分仓
FACTOR_WEIGHTS = {"ep": 0.4, "amihud": 0.3, "div_yield": 0.3}
TARGET_VOL = 0.20
VOL_WINDOW = 60
MA_N = 250

# 成本
STAMP_DUTY = 0.0005   # 印花税 万分之五，卖出
COMMISSION = 0.00012  # 佣金 万分之一点二（你的账户），双边

# 风险线
RISK_LINE = -0.20
RISK_LINE_HARD = -0.25

# 基准指数
BENCHMARKS = {"上证指数": "000001.SH", "沪深300": "000300.SH"}
