import json
import os
from collections import defaultdict
from typing import Dict, List
from pathlib import Path

from ..config.settings import (
    DATA_DIR, DATA_FILE, CACHE_FILE, ALIAS_FILE, 
    RATE_LIMIT_FILE, REVIEW_CACHE_FILE, SILENT_MODE_FILE
)
from ..models.schemas import (
    GroupSubscriptions, ShopInfo, ShopCache, 
    GlobalAliases, ReviewCache, SilentModeConfig
)

# 初始化数据存储目录
os.makedirs(DATA_DIR, exist_ok=True)

class DataManager:
    @staticmethod
    def load_subscriptions() -> Dict[int, GroupSubscriptions]:
        if not DATA_FILE.exists():
            return defaultdict(GroupSubscriptions)
        
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            result = defaultdict(GroupSubscriptions)
            for group_id_str, group_data in data.items():
                group_id = int(group_id_str)
                subs = GroupSubscriptions()
                
                # 加载shops
                for shop_id_str, shop_data in group_data["shops"].items():
                    shop_id = int(shop_id_str)
                    subs.shops[shop_id] = ShopInfo(
                        id=shop_id,
                        last_number=shop_data["last_number"]
                    )
                
                result[group_id] = subs
            
            return result
        except Exception as e:
            print(f"加载数据失败: {str(e)}")
            return defaultdict(GroupSubscriptions)

    @staticmethod
    def save_subscriptions(data: Dict[int, GroupSubscriptions]):
        try:
            serializable_data = {
                str(group_id): group_subs.to_dict()
                for group_id, group_subs in data.items()
            }
            
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存数据失败: {str(e)}")

    @staticmethod
    def load_shop_cache() -> ShopCache:
        if not CACHE_FILE.exists():
            return ShopCache()
        
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ShopCache.from_dict(data)
        except Exception as e:
            print(f"加载机厅缓存失败: {str(e)}")
            return ShopCache()

    @staticmethod
    def save_shop_cache(cache: ShopCache):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存机厅缓存失败: {str(e)}")

    @staticmethod
    def load_global_aliases() -> GlobalAliases:
        if not ALIAS_FILE.exists():
            return GlobalAliases()
        
        try:
            with open(ALIAS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return GlobalAliases.from_dict(data)
        except Exception as e:
            print(f"加载全局简称失败: {str(e)}")
            return GlobalAliases()

    @staticmethod
    def save_global_aliases(aliases: GlobalAliases):
        try:
            with open(ALIAS_FILE, "w", encoding="utf-8") as f:
                json.dump(aliases.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存全局简称失败: {str(e)}")

    @staticmethod
    def load_review_cache() -> ReviewCache:
        if not REVIEW_CACHE_FILE.exists():
            return ReviewCache()
        
        try:
            with open(REVIEW_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ReviewCache.from_dict(data)
        except Exception as e:
            print(f"加载待审核机厅缓存失败: {str(e)}")
            return ReviewCache()

    @staticmethod
    def save_review_cache(cache: ReviewCache):
        try:
            with open(REVIEW_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存待审核机厅缓存失败: {str(e)}")

    @staticmethod
    def load_silent_mode() -> SilentModeConfig:
        if not SILENT_MODE_FILE.exists():
            return SilentModeConfig()
        
        try:
            with open(SILENT_MODE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return SilentModeConfig.from_dict(data)
        except Exception as e:
            print(f"加载静默模式配置失败: {str(e)}")
            return SilentModeConfig()
        
    @staticmethod
    def save_silent_mode(config: SilentModeConfig):
        try:
            with open(SILENT_MODE_FILE, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存静默模式配置失败: {str(e)}")

    @staticmethod
    def load_rate_limit_data() -> Dict[str, Dict[str, List[float]]]:
        if not RATE_LIMIT_FILE.exists():
            return {}
        
        try:
            with open(RATE_LIMIT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"加载速率限制数据失败: {str(e)}")
            return {}

    @staticmethod
    def save_rate_limit_data(data: Dict[str, Dict[str, List[float]]]):
        try:
            with open(RATE_LIMIT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存速率限制数据失败: {str(e)}")
            
    @staticmethod
    def load_report_stats():
        try:
            with open(DATA_DIR / "report_stats.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {
                "daily_stats": {},
                "user_stats": {},
                "last_update": 0
            }

    @staticmethod
    def save_report_stats(stats):
        try:
            with open(DATA_DIR / "report_stats.json", "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存上报统计失败: {str(e)}")
