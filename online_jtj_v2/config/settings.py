from pathlib import Path

# 数据存储路径
# 注意：这里需要确保路径相对于插件目录是正确的，或者使用绝对路径
# 在原始代码中是 Path(__file__).parent / "data"
# 重构后，如果在 config/settings.py 中，data 目录可能在 ../data 或者插件根目录下的 data
# 假设 data 目录位于 online_jtj_v2/data

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "subscriptions.json"
CACHE_FILE = DATA_DIR / "shop_cache.json"
ALIAS_FILE = DATA_DIR / "aliases.json"
RATE_LIMIT_FILE = DATA_DIR / "rate_limit.json"
REVIEW_CACHE_FILE = DATA_DIR / "review_cache.json"
SILENT_MODE_FILE = DATA_DIR / "silent_mode.json"

# 刷榜检测配置
RATE_LIMIT_COUNT = 3  # 1分钟内允许的最大上报次数
RATE_LIMIT_WINDOW = 60  # 时间窗口(秒)
BAN_DURATION = 300  # 封禁时长(秒)

# API 配置
API_URL = ""  # 国内 "https://api.wenuu.cn" 海外 "https://qy.wenuu.cn"
API_KEY = ""  # 替换为 "浙里有mai" 小程序的API key

# 审核机厅用户配置
SUPER_USER_ID = "5359401" # "浙里有mai" 小程序的作者大人
SUPER_USER_ID2 = "" # bot主的qq号
