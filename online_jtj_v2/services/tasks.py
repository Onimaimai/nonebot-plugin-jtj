import asyncio
from ..state import group_subscriptions, shop_cache
from ..services.api_client import ApiClient
from ..services.data_manager import DataManager

async def update_cache_task():
    """定时更新缓存数据的任务"""
    while True:
        try:
            print("开始定时更新缓存数据...")
            
            # 更新所有已订阅机厅的缓存
            for group_id, subs in group_subscriptions.items():
                for shop_id in subs.shops:
                    await ApiClient.get_shop_by_id(shop_id)
            
            print("缓存数据更新完成")
            
            # 保存更新后的缓存
            DataManager.save_shop_cache(shop_cache)
            
            # 每1分钟更新一次
            await asyncio.sleep(60)
        except Exception as e:
            print(f"更新缓存数据失败: {str(e)}")
            # 出错后等待1分钟再试
            await asyncio.sleep(60)
