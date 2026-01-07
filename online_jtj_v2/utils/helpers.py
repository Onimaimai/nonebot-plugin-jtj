import re
import time
from typing import Optional

def extract_time_from_source(shop_source: str) -> Optional[float]:
    """从shop_source中提取时间（当天的秒数），返回时间戳（当天0点起的秒数），失败返回None"""
    match = re.search(r"时间：(\d{2}):(\d{2}):(\d{2})", shop_source)
    if not match:
        return None
    h, m, s = map(int, match.groups())
    return h * 3600 + m * 60 + s

def get_status_symbol_by_source(shop_source: str) -> str:
    """根据shop_source中的时间与当前时间的差，返回状态符号"""
    t = extract_time_from_source(shop_source)
    if t is None:
        return ""  # 未知
    now = time.localtime()
    now_sec = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
    diff = now_sec - t
    if diff < 0:
        diff += 24 * 3600  # 跨天
    hours = diff / 3600
    if hours <= 1:
        return "🟩 1小时内"
    elif hours <= 2:
        return "🟨 1-2小时"
    elif hours > 2:
        return "🟥 2小时前"
    else:
        return ""

def get_number_color_symbol(number: int) -> str:
    """根据人数返回颜色符号"""
    if number == 0:
        return "🟩"
    elif number <= 6:
        return "🟨"
    elif number <= 12:
        return "🟥"
    else:
        return ""

def parse_update_command(text: str) -> Optional[tuple]:
    """解析更新指令，返回(简称, 人数变化, 操作类型)"""
    # 匹配三种格式：简称+数字、简称-数字、简称数字
    match = re.match(r"^(.+?)([+-]?)(\d+)$", text.strip())
    if not match:
        return None
    
    alias, operator, num_str = match.groups()
    try:
        number = int(num_str)
    except ValueError:
        return None
    
    if operator == "+":
        return (alias, number, "add")
    elif operator == "-":
        return (alias, -number, "subtract")
    else:
        return (alias, number, "set")
