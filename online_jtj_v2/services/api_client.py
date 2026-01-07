import httpx
import time
import json
from typing import Optional, List, Any, Dict

from ..config.settings import API_URL, API_KEY
from ..state import shop_cache
from ..services.data_manager import DataManager

class ApiClient:
    # 默认超时设置
    TIMEOUT = 10.0

    @staticmethod
    async def _get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """通用GET请求处理"""
        try:
            async with httpx.AsyncClient(timeout=ApiClient.TIMEOUT) as client:
                response = await client.get(f"{API_URL}{endpoint}", params=params)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            print(f"API请求超时: {endpoint}")
        except httpx.HTTPStatusError as e:
            print(f"API请求错误 {e.response.status_code}: {endpoint}")
        except Exception as e:
            print(f"API请求异常: {str(e)} - {endpoint}")
        return None

    @staticmethod
    async def get_shop_by_id(shop_id: int) -> Optional[dict]:
        """根据机厅ID获取单个机厅信息"""
        # 1. 检查缓存
        if shop_id in shop_cache.shop_data:
            last_update = shop_cache.last_update.get(f"shop_{shop_id}", 0)
            if time.time() - last_update < 60:  # 缓存有效期 60秒
                return shop_cache.shop_data[shop_id]
        
        # 2. 从API获取
        data = await ApiClient._get("/maihere/query/getData_solo.php", params={"id": shop_id})
        
        if isinstance(data, dict):
            # 更新缓存
            shop_cache.shop_data[shop_id] = data
            shop_cache.last_update[f"shop_{shop_id}"] = time.time()
            DataManager.save_shop_cache(shop_cache)
            return data
            
        # 3. API失败时尝试返回过期缓存
        if shop_id in shop_cache.shop_data:
            print(f"API失败，使用过期缓存: shop_{shop_id}")
            return shop_cache.shop_data[shop_id]
            
        return None

    @staticmethod
    async def update_shop_number(shop_id: int, number: int, source: str) -> bool:
        """更新机厅人数"""
        # 乐观更新：先更新本地缓存，让用户立即看到反馈
        if shop_id in shop_cache.shop_data:
            shop_cache.shop_data[shop_id]["shop_number"] = number
            shop_cache.shop_data[shop_id]["shop_source"] = source
            shop_cache.last_update[f"shop_{shop_id}"] = time.time()
            DataManager.save_shop_cache(shop_cache)
        
        # 发送请求
        try:
            async with httpx.AsyncClient(timeout=ApiClient.TIMEOUT) as client:
                response = await client.get(
                    f"{API_URL}/maihere/upload/uploadData.php",
                    params={
                        "id": shop_id,
                        "number": number,
                        "source": source,
                        "key": API_KEY,
                        "uptime": int(time.time())
                    }
                )
                response.raise_for_status()
                return True
        except Exception as e:
            print(f"更新机厅人数API失败: {str(e)}")
            # 注意：如果API失败，本地缓存已经更新了，这保证了用户体验，但可能导致数据不一致。
            # 考虑到这是人数展示，短暂的不一致是可以接受的。
            return False

    @staticmethod
    async def get_city_shops(city_name: str) -> Optional[List[dict]]:
        """根据城市名获取该城市所有机厅信息"""
        # 1. 检查缓存
        if city_name in shop_cache.city_shops:
            last_update = shop_cache.last_update.get(f"city_{city_name}", 0)
            if time.time() - last_update < 60:  
                return shop_cache.city_shops[city_name]
        
        # 2. 从API获取城市ID
        city_data = await ApiClient._get("/maihere/query/queryCity.php", params={"name": city_name})
        
        if not city_data or not isinstance(city_data, list):
            # 尝试使用缓存（即使过期）
            if city_name in shop_cache.city_shops:
                 return shop_cache.city_shops[city_name]
            return None
            
        # 提取城市ID逻辑
        city_id = None
        first_item = city_data[0]
        
        if isinstance(first_item, dict):
            city_id = first_item.get("city_id") or first_item.get("id")
        elif isinstance(first_item, str):
            try:
                parsed = json.loads(first_item)
                if isinstance(parsed, dict):
                    city_id = parsed.get("city_id") or parsed.get("id")
            except:
                pass
        
        if not city_id:
             return None

        # 3. 获取城市机厅列表
        shop_data = await ApiClient._get("/maihere/query/getData_city.php", params={"cityid": city_id})
        
        if isinstance(shop_data, dict) and "error" in shop_data:
            return None
            
        if not isinstance(shop_data, list):
            return None
        
        # 处理数据
        processed_shops = []
        for shop in shop_data:
            if isinstance(shop, dict):
                processed_shops.append(shop)
            elif isinstance(shop, str):
                try:
                    parsed = json.loads(shop)
                    if isinstance(parsed, dict):
                        processed_shops.append(parsed)
                except:
                    pass
        
        # 更新缓存
        shop_cache.city_shops[city_name] = processed_shops
        shop_cache.last_update[f"city_{city_name}"] = time.time()
        
        # 同时更新单个机厅缓存
        for shop in processed_shops:
            if "id" in shop:
                sid = shop["id"]
                shop_cache.shop_data[sid] = shop
                shop_cache.last_update[f"shop_{sid}"] = time.time()
        
        DataManager.save_shop_cache(shop_cache)
        return processed_shops