import time
from typing import Tuple
from ..config.settings import RATE_LIMIT_COUNT, RATE_LIMIT_WINDOW, BAN_DURATION
from ..services.data_manager import DataManager
from ..state import rate_limit_data

class RateLimiter:
    @staticmethod
    def check_rate_limit(group_id: int, user_id: str) -> Tuple[bool, str]:
        """
        检查是否超过速率限制
        返回: (是否允许通过, 拒绝原因)
        """
        current_time = time.time()
        
        # 使用内存中的 state.rate_limit_data，而不是每次都加载文件
        group_id_str = str(group_id)
        
        if group_id_str not in rate_limit_data:
            rate_limit_data[group_id_str] = {}
        
        if user_id not in rate_limit_data[group_id_str]:
            rate_limit_data[group_id_str][user_id] = {"timestamps": [], "banned_until": 0}
        
        user_data = rate_limit_data[group_id_str][user_id]
        
        # 检查是否被封禁
        if current_time < user_data["banned_until"]:
            remaining_time = int(user_data["banned_until"] - current_time)
            return False, f"操作过于频繁，请等待{remaining_time}秒后再试"
        
        # 清理过期的时间戳 (仅保留窗口内的时间戳)
        user_data["timestamps"] = [
            ts for ts in user_data["timestamps"] 
            if current_time - ts <= RATE_LIMIT_WINDOW
        ]
        
        # 检查是否超过速率限制
        if len(user_data["timestamps"]) >= RATE_LIMIT_COUNT:
            # 封禁用户
            user_data["banned_until"] = current_time + BAN_DURATION
            DataManager.save_rate_limit_data(rate_limit_data)
            return False, f"操作过于频繁，请等待{BAN_DURATION}秒后再试"
        
        # 记录当前时间戳
        user_data["timestamps"].append(current_time)
        
        # 保存更新 (为了性能，这里可以选择异步保存或者不每次都保存，但为了数据安全暂时保持每次保存)
        # 考虑到频率限制触发不频繁，每次有效操作保存一次是可以接受的
        DataManager.save_rate_limit_data(rate_limit_data)
        
        return True, ""