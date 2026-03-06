import asyncio
import json
import time
import re
import httpx
from datetime import datetime

from astrbot.api.all import *
from astrbot.api.message_components import *

# 导入本地模块
from .state import group_subscriptions, global_aliases, silent_mode_config, review_cache
from .services.api_client import ApiClient
from .services.data_manager import DataManager
from .services.rate_limiter import RateLimiter
from .services.tasks import update_cache_task
from .utils.helpers import get_status_symbol_by_source, get_number_color_symbol, parse_update_command
from .config.settings import API_URL, DATA_DIR, SUPER_USER_ID, SUPER_USER_ID2, API_KEY
from .models.schemas import ShopInfo, GroupSubscriptions

@register("jtj", "Onimaimai", "机厅查询与更新", "2.1.2")
class JTJPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 启动定时缓存任务
        asyncio.create_task(update_cache_task())
        # 用于记录地图生成 CD
        self.user_last_map_time = {}

    # ==========================
    # 核心查询功能
    # ==========================
    @command("jtj", aliases=["查询机厅"])
    async def handle_jtj(self, event: AstrMessageEvent, identifier: str = ""):
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        # 兼容方式获取是否被 at
        is_at_me = any(isinstance(comp, At) for comp in event.message_obj.message)
        should_send = group_id not in silent_mode_config.silent_groups or is_at_me
        identifier = identifier.strip()

        # --- Case 1: 查询本群订阅 ---
        if not identifier:
            subs = group_subscriptions.get(group_id)
            if not subs or not subs.shops:
                if should_send:
                    yield event.plain_result("本群尚未订阅任何机厅，请使用 '订阅机厅 ID' 进行订阅。")
                return

            shop_ids = list(subs.shops.keys())
            shops_data_map = await ApiClient.get_shops_by_ids(shop_ids)

            messages = []
            for shop_id, shop_info in subs.shops.items():
                shop_data = shops_data_map.get(shop_id)
                if shop_data:
                    shop_info.last_number = int(shop_data.get("shop_number", 0))
                    status_symbol = get_status_symbol_by_source(shop_data.get("shop_source", ""))
                    shop_name = shop_data.get('shop_name', f'机厅{shop_id}')
                    source = shop_data.get('shop_source', '未知来源')
                    messages.append(f"{shop_name}({shop_id})\n当前：{shop_info.last_number} 人 {status_symbol}")
                else:
                    messages.append(f"机厅{shop_id} (数据获取失败)")

            if should_send and messages:
                yield event.plain_result("【本群订阅机厅查询结果】\n\n" + "\n\n".join(messages))
            return

        # --- Case 2: 按简称查询 ---
        if identifier in global_aliases.alias_to_ids:
            shop_ids = global_aliases.alias_to_ids[identifier]
            subs = group_subscriptions.get(group_id)
            if not subs:
                 if should_send:
                    yield event.plain_result(f"本群未订阅简称 '{identifier}' 对应的任何机厅。")
                 return

            subscribed_shop_ids = [sid for sid in shop_ids if sid in subs.shops]
            if subscribed_shop_ids:
                shops_data_map = await ApiClient.get_shops_by_ids(subscribed_shop_ids)
                messages = []
                for shop_id in subscribed_shop_ids:
                    shop_data = shops_data_map.get(shop_id)
                    if shop_data:
                        number = int(shop_data.get('shop_number', 0))
                        status_symbol = get_status_symbol_by_source(shop_data.get("shop_source", ""))
                        shop_name = shop_data.get('shop_name', f'机厅{shop_id}')
                        source = shop_data.get('shop_source', '未知')
                        messages.append(f"{shop_name}({shop_id})\n当前：{number} 人 {status_symbol}\n来源：{source}")
                
                if should_send and messages:
                    yield event.plain_result(f"【简称 '{identifier}' 查询结果】\n\n" + "\n\n".join(messages))
                return
            else:
                if should_send:
                    yield event.plain_result(f"本群未订阅简称 '{identifier}' 对应的任何机厅。")
                return

        # --- Case 3: 按ID查询 ---
        if identifier.isdigit():
            shop_id = int(identifier)
            shop_data = await ApiClient.get_shop_by_id(shop_id)
            if should_send:
                if shop_data:
                    number = int(shop_data.get('shop_number', 0))
                    status_symbol = get_status_symbol_by_source(shop_data.get("shop_source", ""))
                    shop_name = shop_data.get('shop_name', f'机厅{shop_id}')
                    source = shop_data.get('shop_source', '未知')
                    yield event.plain_result(f"{shop_name}({shop_id})\n当前：{number} 人 {status_symbol}\n来源：{source}")
                else:
                    yield event.plain_result(f"未找到ID为{shop_id}的机厅信息")
            return
        
        # --- Case 4: 按城市名查询 ---
        shop_data_list = await ApiClient.get_city_shops(identifier)
        if not shop_data_list:
            if should_send:
                yield event.plain_result(f"没有查到城市 '{identifier}' 的机厅信息，请确认城市名是否正确。")
            return
        
        messages = [f"城市 '{identifier}' 的机厅信息："]
        for shop in shop_data_list:
            if isinstance(shop, dict):
                try:
                    shop_id = shop.get('id', '未知ID')
                    shop_name = shop.get('shop_name', '未知机厅')
                    shop_num = int(shop.get('shop_number', 0))
                    status_symbol = get_status_symbol_by_source(shop.get('shop_source', ''))
                    messages.append(f"{shop_name}({shop_id})\n{shop_num} 人 {status_symbol}")
                except Exception:
                    continue
        
        if should_send:
            yield event.plain_result("\n".join(messages))

    @command("附近机厅")
    async def nearby_shops(self, event: AstrMessageEvent, lat: str = "", lng: str = ""):
        if not lat or not lng:
            yield event.plain_result("平台限制无法直接获取位置卡片。请按格式提供经纬度，例如：/附近机厅 30.25 120.16")
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{API_URL}/maihere/location/distance.php", params={"LON": lng, "LAT": lat})
                data = response.json()
                if not data:
                    yield event.plain_result("附近没有找到机厅。")
                    return
                messages = ["附近的机厅有："]
                for shop in data:
                    shop_name = shop.get('shop_name', '未知机厅')
                    distance = shop.get('distance', '未知')
                    shop_address = shop.get('shop_address', '未知地址')
                    messages.append(f"【{shop_name}】\n距离：{distance}\n地址：{shop_address}")
                yield event.plain_result("\n\n".join(messages))
        except Exception as e:
            yield event.plain_result(f"查询附近机厅失败: {str(e)}")

    @command("机厅地图", aliases=["出勤地图"])
    async def nearby_shops_map(self, event: AstrMessageEvent, lat: str = "", lng: str = "", radius: str = "4"):
        if not lat or not lng:
            yield event.plain_result("请按格式提供经纬度，例如：/机厅地图 30.25 120.16 4")
            return
            
        user_id = event.get_sender_id()
        current_time = time.time()
        if user_id in self.user_last_map_time and current_time - self.user_last_map_time[user_id] < 15:
            yield event.plain_result("地图生成指令冷却中，请稍后再试（15秒CD）。")
            return

        try:
            api_params = {"LON": lng, "LAT": lat, "radius": int(radius)}
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{API_URL}/maihere/location/pic.php", params=api_params)
                data = response.json()
                if "map_url" in data:
                    self.user_last_map_time[user_id] = current_time
                    map_url = data["map_url"]
                    note = data.get("note", "")
                    chain = [Plain(f"{note}\n"), Image.fromURL(map_url)]
                    yield event.chain_result(chain)
                else:
                    yield event.plain_result(data.get("note", "地图生成失败，API未返回有效URL。"))
        except httpx.ReadTimeout:
            yield event.plain_result("地图生成超时，请稍后再试。")
        except Exception as e:
            yield event.plain_result(f"生成机厅地图失败: {str(e)}")

    @command("jt贡献榜", aliases=["jt贡献排行", "jt上报排行", "jt上报榜"])
    async def contribution_rank(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        date = datetime.now().strftime("%Y-%m-%d")
        try:
            stats = DataManager.load_report_stats()
            if date not in stats["daily_stats"] or str(group_id) not in stats["daily_stats"][date]:
                yield event.plain_result("今日暂无上报数据，快去更新机厅人数吧！")
                return
            group_stats = stats["daily_stats"][date][str(group_id)]
            user_data = []
            for user_id, count in group_stats.items():
                nickname = stats["user_stats"].get(user_id, {}).get("nickname", "匿名用户").split("(")[0]
                user_data.append((nickname, int(count)))
            user_data.sort(key=lambda x: x[1], reverse=True)
            if not user_data:
                yield event.plain_result("今日暂无上报数据。")
                return
            rank_text = f"【今日机厅上报榜】\n"
            for i, (nickname, count) in enumerate(user_data[:10]):
                prefix = f"{i+1}. "
                if i == 0: prefix = "🥇"
                elif i == 1: prefix = "🥈"
                elif i == 2: prefix = "🥉"
                rank_text += f"{prefix} {nickname}: {count}次\n"
            yield event.plain_result(rank_text.strip())
        except Exception as e:
            yield event.plain_result("生成贡献榜失败，请稍后再试。")

    # ==========================
    # 订阅与简称管理
    # ==========================
    @command("订阅机厅")
    async def subscribe(self, event: AstrMessageEvent, ids_str: str):
        if not ids_str:
            yield event.plain_result("请输入要订阅的机厅ID，多个ID用空格分隔。")
            return
        try:
            shop_ids = [int(id_str) for id_str in ids_str.replace("，", " ").replace(",", " ").split()]
        except ValueError:
            yield event.plain_result("机厅ID必须是数字，多个ID用空格分隔。")
            return
        
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        if group_id not in group_subscriptions:
            group_subscriptions[group_id] = GroupSubscriptions()
            
        subs = group_subscriptions[group_id]
        results, has_changes = [], False
        
        for shop_id in shop_ids:
            shop_data = await ApiClient.get_shop_by_id(shop_id)
            shop_name = shop_data.get('shop_name') if shop_data else "未知机厅"
            
            if shop_id in subs.shops:
                results.append(f"✅ {shop_name}({shop_id}) - 已订阅")
                continue
            if not shop_data:
                results.append(f"⚠️ {shop_id} - 机厅不存在或无法获取信息")
                continue
            
            subs.shops[shop_id] = ShopInfo(id=shop_id)
            results.append(f"🎉 {shop_name}({shop_id}) - 订阅成功")
            has_changes = True
            
        if has_changes:
            DataManager.save_subscriptions(group_subscriptions)
        yield event.plain_result("\n".join(results))

    @command("退订机厅")
    async def unsubscribe(self, event: AstrMessageEvent, ids_str: str):
        if not ids_str:
            yield event.plain_result("请输入要取消订阅的机厅ID，多个ID用空格分隔。")
            return
        try:
            shop_ids = [int(id_str) for id_str in ids_str.replace("，", " ").replace(",", " ").split()]
        except ValueError:
            yield event.plain_result("机厅ID必须是数字，多个ID用空格分隔。")
            return

        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        if group_id not in group_subscriptions:
             yield event.plain_result("本群尚未订阅任何机厅。")
             return

        subs = group_subscriptions[group_id]
        results, has_changes = [], False

        for shop_id in shop_ids:
            shop_data = await ApiClient.get_shop_by_id(shop_id)
            shop_name = shop_data.get('shop_name') if shop_data else f"机厅{shop_id}"
            if shop_id not in subs.shops:
                results.append(f"⚠️ {shop_name} - 未订阅")
                continue
            subs.shops.pop(shop_id)
            results.append(f"🗑️ {shop_name} - 取消订阅成功")
            has_changes = True
        
        if has_changes:
            DataManager.save_subscriptions(group_subscriptions)
        yield event.plain_result("\n".join(results))

    @command("订阅城市")
    async def subscribe_city(self, event: AstrMessageEvent, city_name: str):
        if not city_name:
            yield event.plain_result("请输入要订阅的城市名称。")
            return
            
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        if group_id not in group_subscriptions:
            group_subscriptions[group_id] = GroupSubscriptions()
        subs = group_subscriptions[group_id]
        
        shop_data = await ApiClient.get_city_shops(city_name)
        if not shop_data:
            yield event.plain_result(f"没有查到 {city_name} 的机厅信息，请检查城市名称是否正确。")
            return
        
        results, new_subscriptions, already_subscribed = [], 0, 0
        for shop in shop_data:
            if not isinstance(shop, dict) or "id" not in shop:
                continue
            shop_id = shop["id"]
            shop_name = shop.get("shop_name", f"机厅{shop_id}")
            if shop_id in subs.shops:
                already_subscribed += 1
                continue
            subs.shops[shop_id] = ShopInfo(id=shop_id)
            new_subscriptions += 1
            results.append(f"{shop_name}({shop_id})")
        
        if new_subscriptions > 0:
            DataManager.save_subscriptions(group_subscriptions)
            summary = f"成功订阅 {city_name} 的 {new_subscriptions} 个机厅"
            if already_subscribed > 0: summary += f"，已有 {already_subscribed} 个机厅被订阅"
            yield event.plain_result(f"{summary}。\n包括：{', '.join(results[:10])} 等。" if len(results) > 10 else f"{summary}：\n" + "\n".join(results))
        else:
            yield event.plain_result(f"已订阅 {city_name} 的所有机厅，共 {already_subscribed} 个。" if already_subscribed > 0 else f"未能订阅 {city_name} 的任何机厅。")

    @command("退订城市", aliases=["取消订阅城市"])
    async def unsubscribe_city(self, event: AstrMessageEvent, city_name: str):
        if not city_name:
            yield event.plain_result("请输入要取消订阅的城市名称。")
            return
            
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        if group_id not in group_subscriptions:
            yield event.plain_result(f"本群尚未订阅任何机厅。")
            return
        subs = group_subscriptions[group_id]
        
        shop_data = await ApiClient.get_city_shops(city_name)
        if not shop_data:
            yield event.plain_result(f"没有查到 {city_name} 的机厅信息。")
            return
        
        results, unsubscribed, not_subscribed = [], 0, 0
        for shop in shop_data:
            if not isinstance(shop, dict) or "id" not in shop: continue
            shop_id = shop["id"]
            if shop_id not in subs.shops:
                not_subscribed += 1
                continue
            subs.shops.pop(shop_id)
            unsubscribed += 1
            results.append(f"{shop.get('shop_name', f'机厅{shop_id}')}")
            
        if unsubscribed > 0:
            DataManager.save_subscriptions(group_subscriptions)
            summary = f"成功取消订阅 {city_name} 的 {unsubscribed} 个机厅"
            yield event.plain_result(f"{summary}。" if len(results) > 10 else f"{summary}：\n" + ", ".join(results))
        else:
            yield event.plain_result(f"本群未订阅 {city_name} 的任何机厅。" if not_subscribed > 0 else f"未能取消订阅 {city_name} 的任何机厅。")

    @command("添加简称")
    async def add_alias(self, event: AstrMessageEvent, shop_id_str: str, alias: str):
        if not shop_id_str.isdigit() or not alias:
            yield event.plain_result("格式错误。正确格式：添加简称 <机厅ID> <简称>")
            return
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        shop_id = int(shop_id_str)
        subs = group_subscriptions.get(group_id)
        
        if subs and shop_id not in subs.shops:
            yield event.plain_result(f"未订阅ID为 {shop_id} 的机厅，请先订阅后再设置简称。")
            return
        if alias not in global_aliases.alias_to_ids:
            global_aliases.alias_to_ids[alias] = []
        if shop_id in global_aliases.alias_to_ids[alias]:
            yield event.plain_result(f"机厅 {shop_id} 已经有简称: {alias}")
            return
            
        global_aliases.alias_to_ids[alias].append(shop_id)
        DataManager.save_global_aliases(global_aliases)
        shop_data = await ApiClient.get_shop_by_id(shop_id)
        shop_name = shop_data.get('shop_name') if shop_data else f"机厅{shop_id}"
        yield event.plain_result(f"✅ 已为 {shop_name}({shop_id}) 添加简称: {alias}")

    @command("删除简称")
    async def remove_alias(self, event: AstrMessageEvent, shop_id_str: str, alias: str):
        if not shop_id_str.isdigit() or not alias:
            yield event.plain_result("格式错误。正确格式：删除简称 <机厅ID> <简称>")
            return
        shop_id = int(shop_id_str)
        if shop_id not in global_aliases.alias_to_ids.get(alias, []):
            yield event.plain_result(f"机厅 {shop_id} 没有简称: {alias}")
            return
            
        global_aliases.alias_to_ids[alias].remove(shop_id)
        if not global_aliases.alias_to_ids[alias]:
            global_aliases.alias_to_ids.pop(alias)
        DataManager.save_global_aliases(global_aliases)
        yield event.plain_result(f"🗑️ 已删除机厅 {shop_id} 的简称: {alias}")

    @command("查询简称")
    async def list_aliases(self, event: AstrMessageEvent, shop_id_str: str = ""):
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        subs = group_subscriptions.get(group_id)
        
        if shop_id_str:
            if not shop_id_str.isdigit():
                yield event.plain_result("机厅ID必须是数字。")
                return
            shop_id = int(shop_id_str)
            if subs and shop_id not in subs.shops:
                yield event.plain_result(f"未订阅ID为 {shop_id} 的机厅，无法查看其简称。")
                return
            
            shop_aliases = [alias for alias, ids in global_aliases.alias_to_ids.items() if shop_id in ids]
            shop_data = await ApiClient.get_shop_by_id(shop_id)
            shop_name = shop_data['shop_name'] if shop_data else "未知机厅"
            
            if not shop_aliases:
                yield event.plain_result(f"{shop_name}({shop_id}) 没有设置简称。")
            else:
                yield event.plain_result(f"{shop_name}({shop_id}) 的简称:\n" + "\n".join(shop_aliases))
        else:
            if not subs or not subs.shops:
                yield event.plain_result("本群尚未订阅任何机厅。")
                return
            
            subscribed_shop_ids = set(subs.shops.keys())
            messages = []
            for alias, shop_ids in global_aliases.alias_to_ids.items():
                group_shop_ids = [str(sid) for sid in shop_ids if sid in subscribed_shop_ids]
                if group_shop_ids:
                    messages.append(f"• {alias}: {', '.join(group_shop_ids)}")
            
            if not messages:
                yield event.plain_result("本群订阅的机厅均未设置简称。")
            else:
                yield event.plain_result("本群机厅简称列表:\n" + "\n".join(messages))

    # ==========================
    # 管理与审核功能
    # ==========================
    @command("申请机厅")
    async def apply_shop(self, event: AstrMessageEvent, shop_name: str = "", city: str = ""):
        if not shop_name or not city:
            yield event.plain_result("请输入机厅名称和所在城市，例如：/申请机厅 新机厅 杭州")
            return
            
        user_id = event.get_sender_id()
        user_nickname = event.message_obj.sender.nickname or f"用户{user_id}"
        group_id = event.message_obj.group_id
        
        apply_info = f"收到新的机厅申请：\n机厅名称：{shop_name}\n所在城市：{city}\n申请者：{user_nickname}({user_id})\n来源群聊：{group_id}"
        print(f"[机厅插件] {apply_info}")
        yield event.plain_result("成功提交机厅申请，请等待管理员通过系统查看（注意：建议使用 /添加机厅 携带经纬度直接进入API系统申请）。")

    @command("添加机厅", aliases=["新建机厅"])
    async def add_shop_location(self, event: AstrMessageEvent, shop_name: str = "", city_name: str = "", address: str = "", lat: str = "", lng: str = ""):
        if not all([shop_name, city_name, address, lat, lng]):
            yield event.plain_result("请提供完整信息！格式：/添加机厅 <店名> <城市名> <地址> <纬度> <经度>\n例如: /添加机厅 测试店 杭州市 某某路 30.2 120.1")
            return
            
        city_shops = await ApiClient.get_city_shops(city_name)
        if not city_shops or not isinstance(city_shops, list):
            yield event.plain_result(f"未能获取城市 {city_name} 的机厅信息，无法添加。")
            return
        
        city_id = None
        for shop in city_shops:
            if isinstance(shop, dict) and ("city_id" in shop or "id" in shop):
                city_id = shop.get("city_id") or shop.get("id")
                break
        if not city_id:
            yield event.plain_result(f"未能获取城市 {city_name} 的ID，无法添加。")
            return

        api_url = f"{API_URL}/maihere/location/add.php"
        params = {
            "shop_name": shop_name,
            "shop_address": address,
            "shop_city": str(city_id),
            "LON": lng,
            "LAT": lat,
            "coin": "1",
            "key": API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, params=params)
            text = resp.text.strip()
            try:
                data = json.loads(text.split('}')[0] + '}')
                if "success" in data:
                    yield event.plain_result(f"添加机厅成功：已提交到系统，请等待管理员输入 /审核机厅 处理！")
                elif "error" in data:
                    yield event.plain_result(f"添加机厅失败：{data['error']}")
                else:
                    yield event.plain_result(f"添加机厅未知返回：{data}")
            except Exception as e:
                yield event.plain_result(f"API 返回格式异常: {e}")

    @command("审核机厅")
    async def review_shop(self, event: AstrMessageEvent, pass_id: str = ""):
        user_id = str(event.get_sender_id())
        if user_id not in [SUPER_USER_ID, SUPER_USER_ID2]:
            yield event.plain_result("无权限操作，仅超级用户可用。")
            return
            
        if not pass_id:
            api_url = f"{API_URL}/maihere/location/get_review_shop.php"
            async with httpx.AsyncClient() as client:
                resp = await client.get(api_url)
                data = resp.json()
                review_list = data.get("data") if isinstance(data, dict) else data
                if not review_list:
                    yield event.plain_result("当前暂无待审核的机厅。")
                    return
                msg = ["【待审核机厅列表】"]
                for shop in review_list:
                    msg.append(f"ID: {shop.get('id')}\n店名: {shop.get('shop_name')}\n地址: {shop.get('shop_address')}\n")
                yield event.plain_result("\n".join(msg) + "\n\n请发送 '/审核机厅 <ID>' 来通过审核")
        else:
            if not pass_id.isdigit():
                yield event.plain_result("机厅ID必须是数字！")
                return
            api_url = f"{API_URL}/maihere/location/pass.php"
            params = {"pass": pass_id, "key": API_KEY}
            async with httpx.AsyncClient() as client:
                resp = await client.get(api_url, params=params)
                yield event.plain_result(f"机厅ID {pass_id} 操作审核完毕！")

    @command("清空审核机厅")
    async def clear_review_shop(self, event: AstrMessageEvent):
        user_id = str(event.get_sender_id())
        if user_id not in [SUPER_USER_ID, SUPER_USER_ID2]:
            yield event.plain_result("无权限操作，仅超级用户可用。")
            return
            
        api_url = f"{API_URL}/maihere/location/clear_review.php"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(api_url)
                if "成功修改了" in resp.text or "success" in resp.text.lower():
                    yield event.plain_result("清空审核机厅列表成功！")
                else:
                    yield event.plain_result(f"清空审核机厅失败：{resp.text}")
        except Exception as e:
            yield event.plain_result(f"清空审核机厅接口请求失败：{e}")

    @command("静默模式", aliases=["静默"])
    async def silent_mode(self, event: AstrMessageEvent, arg: str = ""):
        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        if not arg:
            is_silent = group_id in silent_mode_config.silent_groups
            yield event.plain_result(f"当前群组静默模式：{'开启' if is_silent else '关闭'}")
            return
            
        if arg in ["开", "开启", "on", "1"]:
            silent_mode_config.silent_groups.add(group_id)
            DataManager.save_silent_mode(silent_mode_config)
            yield event.plain_result("已开启静默模式，机器人将不再主动回复人数消息，但可通过@机器人进行查询。")
        elif arg in ["关", "关闭", "off", "0"]:
            if group_id in silent_mode_config.silent_groups:
                silent_mode_config.silent_groups.remove(group_id)
            DataManager.save_silent_mode(silent_mode_config)
            yield event.plain_result("已关闭静默模式，机器人将正常回复人数消息")
        else:
            yield event.plain_result("参数错误，请使用：/静默模式 开启/关闭")

    # ==========================
    # 人数动态更新监听 (支持指令：简称10, 简称+1, 简称-1, 简称j)
    # ==========================
    @event_message_type(EventMessageType.ALL)
    async def handle_alias_commands(self, event: AstrMessageEvent):
        # 1. 精确提取纯文本内容，完全忽略 At 组件避免干扰前缀匹配
        text = ""
        is_at_me = False
        for comp in event.message_obj.message:
            if isinstance(comp, Plain):
                text += comp.text
            elif isinstance(comp, At):
                is_at_me = True
                
        text = text.strip()

        if not text:
            return

        # 若内容已匹配其他核心指令则直接放行
        if text.startswith(("jtj", "订阅", "退订", "添加", "删除", "查看", "申请", "审核", "静默", "附近", "机厅地图", "/")):
            return

        group_id = event.message_obj.group_id if event.message_obj.group_id else event.session_id
        
        matched_alias = None
        # 确保长简称优先匹配
        sorted_aliases = sorted(global_aliases.alias_to_ids.keys(), key=len, reverse=True)
        
        for alias in sorted_aliases:
            if text.startswith(alias):
                remaining = text[len(alias):].strip()
                if remaining in ['j', '几'] or parse_update_command(alias + remaining):
                    matched_alias = alias
                    break
                matched_alias = alias
                break

        if not matched_alias:
            return
            
        remaining = text[len(matched_alias):].strip()

        # 处理查询指令 (简称 + j/几)
        if remaining in ['j', '几']:
            shop_ids = global_aliases.alias_to_ids.get(matched_alias, [])
            if not shop_ids: return
            subs = group_subscriptions.get(group_id)
            if not subs: return
            subscribed_shop_ids = [sid for sid in shop_ids if sid in subs.shops]
            if not subscribed_shop_ids: return
                
            messages = []
            should_send = group_id not in silent_mode_config.silent_groups or is_at_me
            
            for shop_id in subscribed_shop_ids:
                shop_info = subs.shops[shop_id]
                shop_data = await ApiClient.get_shop_by_id(shop_id)
                if not shop_data: continue
                shop_info.last_number = int(shop_data.get("shop_number", 0))
                status_symbol = get_status_symbol_by_source(shop_data.get("shop_source", ""))
                shop_name = shop_data.get('shop_name', f'机厅{shop_id}')
                source = shop_data.get('shop_source', '未知')
                messages.append(f"{shop_name}({shop_id})\n当前：{shop_info.last_number} 人 {status_symbol}\n来源：{source}")
            
            DataManager.save_subscriptions(group_subscriptions)
            if messages and should_send:
                yield event.plain_result("\n\n".join(messages))
            return

        # 处理更新指令
        update_parsed = parse_update_command(matched_alias + remaining)
        if update_parsed:
            # 解决 await 报错问题，通过 async for 进行分发
            async for ret in self._handle_update_logic(event, group_id, update_parsed, is_at_me):
                yield ret

    async def _handle_update_logic(self, event: AstrMessageEvent, group_id, parsed: tuple, is_at_me: bool):
        alias, number_change, op_type = parsed
        user_id = str(event.get_sender_id())
        
        allowed, reason = RateLimiter.check_rate_limit(group_id, user_id)
        if not allowed:
            yield event.plain_result(reason)
            return
            
        shop_ids = global_aliases.alias_to_ids.get(alias, [])
        if not shop_ids: return
        subs = group_subscriptions.get(group_id)
        if not subs: return
        subscribed_shop_ids = [sid for sid in shop_ids if sid in subs.shops]
        if not subscribed_shop_ids: return
        
        target_shop_id = subscribed_shop_ids[0]
        user_nickname = event.message_obj.sender.nickname or f"用户{user_id}"
        user_str = f"{user_nickname}({user_id})"
        timestamp = datetime.now().strftime("%H:%M:%S")
        source = f"QQ用户 \n时间：{timestamp}"
        
        shop_info = subs.shops[target_shop_id]
        new_number = number_change if op_type == "set" else max(0, shop_info.last_number + number_change)
        
        if new_number > 50:
            yield event.plain_result("禁止恶意上报！")
            return
            
        shop_data = await ApiClient.get_shop_by_id(target_shop_id)
        shop_name = shop_data.get("shop_name", f"机厅{target_shop_id}") if shop_data else f"机厅{target_shop_id}"
        
        if group_id not in silent_mode_config.silent_groups or is_at_me:
            yield event.plain_result(f"✅ 更新成功！\n{shop_name}\n当前：{new_number} 人")
        
        await ApiClient.update_shop_number(target_shop_id, new_number, source)
        shop_info.last_number = new_number
        
        # 统计更新
        today = datetime.now().strftime("%Y-%m-%d")
        stats = DataManager.load_report_stats()
        if today not in stats["daily_stats"]: stats["daily_stats"][today] = {}
        if str(group_id) not in stats["daily_stats"][today]: stats["daily_stats"][today][str(group_id)] = {}
        if user_id not in stats["daily_stats"][today][str(group_id)]: stats["daily_stats"][today][str(group_id)][user_id] = 0
        stats["daily_stats"][today][str(group_id)][user_id] += 1
        
        if user_id not in stats["user_stats"]: stats["user_stats"][user_id] = {"total": 0, "nickname": user_nickname}
        else: stats["user_stats"][user_id]["nickname"] = user_nickname
        stats["user_stats"][user_id]["total"] += 1
        stats["last_update"] = time.time()
        DataManager.save_report_stats(stats)
        
        DataManager.save_subscriptions(group_subscriptions)
