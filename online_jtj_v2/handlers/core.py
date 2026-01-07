from nonebot import on_command
from nonebot.adapters import Message
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, MessageSegment
from nonebot.matcher import Matcher
from nonebot.exception import FinishedException
from datetime import datetime
import json
import time
import httpx

from ..state import group_subscriptions, global_aliases, silent_mode_config
from ..services.api_client import ApiClient
from ..services.data_manager import DataManager
from ..utils.helpers import get_status_symbol_by_source, get_number_color_symbol
from ..config.settings import API_URL, DATA_DIR

jtj = on_command("jtj", aliases={"查询机厅"}, priority=10, block=True)
nearby_shops = on_command("附近机厅", priority=10, block=False)
nearby_shops_map = on_command("机厅地图", aliases={"出勤地图"}, priority=9, block=False)
contribution_rank = on_command("jt贡献榜", aliases={"jt贡献排行", "jt上报排行", "jt上报榜"}, priority=10, block=True)

# Cooldown dictionary for the map command
user_last_map_time = {}

async def send_forward_message(bot: Bot, group_id: int, messages: list[str], title: str = "机厅查询结果"):
    """发送合并转发消息"""
    try:
        forward_nodes = []
        for message in messages:
            forward_nodes.append({
                "type": "node",
                "data": {
                    "name": f"《浙里有mai》小程序",
                    "uin": bot.self_id,
                    "content": [{"type": "text", "data": {"text": message}}]
                }
            })
        
        await bot.call_api(
            "send_group_forward_msg",
            group_id=group_id,
            messages=forward_nodes
        )
        return True
    except Exception as e:
        print(f"发送合并转发消息失败: {str(e)}")
        return False

@jtj.handle()
async def handle_jtj(bot: Bot, event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    identifier = args.extract_plain_text().strip()
    group_id = event.group_id
    should_send = group_id not in silent_mode_config.silent_groups or event.is_tome()

    # 如果是静默模式且未@机器人，则直接忽略（除了某些特殊情况，但在handle里一般已经进入流程了）
    # 注意：on_command默认只要匹配到指令就会触发，不论是否@（除非设置了rule）
    # 这里保持原有逻辑，silent_mode只控制是否发送回复
    
    # --- Case 1: 查询本群订阅 ---
    if not identifier:
        subs = group_subscriptions[group_id]
        if not subs.shops:
            if should_send:
                await matcher.finish("本群尚未订阅任何机厅，请使用 '订阅机厅 ID' 进行订阅。")
            return

        messages = []
        for shop_id, shop_info in subs.shops.items():
            shop_data = await ApiClient.get_shop_by_id(shop_id)
            if shop_data:
                shop_info.last_number = int(shop_data.get("shop_number", 0))
                status_symbol = get_status_symbol_by_source(shop_data.get("shop_source", ""))
                
                shop_name = shop_data.get('shop_name', f'机厅{shop_id}')
                source = shop_data.get('shop_source', '未知来源')
                
                messages.append(
                    f"{shop_name}({shop_id})\n"
                    f"当前：{shop_info.last_number} 人 {status_symbol}\n"
                    f"来源：{source}"
                )
            else:
                 messages.append(f"机厅{shop_id} (数据获取失败)")

        if should_send and messages:
            if len(messages) > 4:
                success = await send_forward_message(bot, group_id, messages, "本群订阅机厅查询结果")
                if not success:
                    await matcher.send("\n\n".join(messages))
            else:
                await matcher.send("\n\n".join(messages))
        return

    # --- Case 2: 按简称查询 ---
    if identifier in global_aliases.alias_to_ids:
        shop_ids = global_aliases.alias_to_ids[identifier]
        subs = group_subscriptions[group_id]
        # 筛选出本群已订阅的机厅
        subscribed_shop_ids = [sid for sid in shop_ids if sid in subs.shops]

        if subscribed_shop_ids:
            messages = []
            for shop_id in subscribed_shop_ids:
                shop_data = await ApiClient.get_shop_by_id(shop_id)
                if shop_data:
                    number = int(shop_data.get('shop_number', 0))
                    status_symbol = get_status_symbol_by_source(shop_data.get("shop_source", ""))
                    shop_name = shop_data.get('shop_name', f'机厅{shop_id}')
                    source = shop_data.get('shop_source', '未知')
                    
                    messages.append(
                        f"{shop_name}({shop_id})\n"
                        f"当前：{number} 人 {status_symbol}\n"
                        f"来源：{source}"
                    )
            
            if should_send and messages:
                if len(messages) > 4:
                    success = await send_forward_message(bot, group_id, messages, f"简称{identifier}机厅查询结果")
                    if not success:
                        await matcher.send("\n\n".join(messages))
                else:
                    await matcher.send("\n\n".join(messages))
            return
        else:
             if should_send:
                 # 虽然是简称，但本群没订阅对应机厅
                 await matcher.finish(f"本群未订阅简称 '{identifier}' 对应的任何机厅。")
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
                
                await matcher.finish(
                    f"{shop_name}({shop_id})\n"
                    f"当前：{number} 人 {status_symbol}\n"
                    f"来源：{source}"
                )
            else:
                await matcher.finish(f"未找到ID为{shop_id}的机厅信息")
        return
    
    # --- Case 4: 按城市名查询 ---
    if should_send:
        await matcher.send(f"正在查询 '{identifier}' 的机厅信息，请稍候...")
    
    shop_data_list = await ApiClient.get_city_shops(identifier)
    
    if not shop_data_list:
        if should_send:
            await matcher.finish(f"没有查到城市 '{identifier}' 的机厅信息，请确认城市名是否正确。")
        return
    
    messages = [f"城市 '{identifier}' 的机厅信息："]
    for shop in shop_data_list:
        if isinstance(shop, dict):
            try:
                shop_id = shop.get('id', '未知ID')
                shop_name = shop.get('shop_name', '未知机厅')
                shop_num = int(shop.get('shop_number', 0))
                status_symbol = get_status_symbol_by_source(shop.get('shop_source', ''))
                
                messages.append(
                    f"{shop_name}({shop_id})\n{shop_num} 人 {status_symbol}"
                )
            except Exception:
                continue
    
    if should_send:
        if len(messages) > 4:
            content_messages = messages[1:] # 第一行是标题
            success = await send_forward_message(bot, group_id, content_messages, f"{identifier}机厅查询结果")
            if not success:
                await matcher.finish("\n".join(messages))
        else:
            await matcher.finish("\n".join(messages))

@nearby_shops.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    await matcher.send("请发送你的位置信息（点击+号 -> 位置）")

@nearby_shops.got("location")
async def handle_nearby_shops_location(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    lat = None
    lng = None
    # 优先解析JSON格式的位置消息 (OneBot v11 标准或部分实现)
    for msg in event.message:
        if msg.type == "json":
            try:
                data = json.loads(msg.data['data'])
                # 支持多种JSON位置格式
                if 'meta' in data:
                    meta = data['meta']
                    if 'Location.Search' in meta:
                        loc = meta['Location.Search']
                    elif 'location' in meta:
                        loc = meta['location']
                    else:
                        continue
                        
                    lat = loc.get("lat")
                    lng = loc.get("lng") or loc.get("lon")
            except Exception:
                pass
        elif msg.type == "location":
            lat = msg.data.get("lat")
            lng = msg.data.get("lon")

    if lat is None or lng is None:
        await matcher.finish("无法获取位置信息，请确保发送的是【位置】消息。")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{API_URL}/maihere/location/distance.php",
                params={"LON": lng, "LAT": lat},
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                await matcher.finish("附近没有找到机厅。")

            messages = ["附近的机厅有："]
            for shop in data:
                shop_name = shop.get('shop_name', '未知机厅')
                distance = shop.get('distance', '未知')
                shop_address = shop.get('shop_address', '未知地址')
                messages.append(f"【{shop_name}】\n距离：{distance}\n地址：{shop_address}")
            
            await matcher.finish("\n\n".join(messages))

    except FinishedException:
        pass
    except Exception as e:
        await matcher.finish(f"查询附近机厅失败: {str(e)}")

@nearby_shops_map.handle()
async def handle_map_prompt(matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    radius = 4  # Default radius
    if args_str and args_str.isdigit():
        radius = int(args_str)
    
    matcher.state["radius"] = radius
    await matcher.send("请发送你的位置信息，用于生成机厅地图。")

@nearby_shops_map.got("location")
async def handle_nearby_shops_map_location(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    user_id = event.get_user_id()
    current_time = time.time()

    # Cooldown check (15s)
    if user_id in user_last_map_time and current_time - user_last_map_time[user_id] < 15:
        await matcher.finish("地图生成指令冷却中，请稍后再试。")
        return

    lat = None
    lng = None
    radius = matcher.state.get("radius", 4)

    # 复用位置解析逻辑 (这里为了独立性再写一遍，实际可抽取到utils)
    for msg in event.message:
        if msg.type == "json":
            try:
                data = json.loads(msg.data['data'])
                if 'meta' in data:
                    meta = data['meta']
                    loc = meta.get('Location.Search') or meta.get('location')
                    if loc:
                        lat = loc.get("lat")
                        lng = loc.get("lng") or loc.get("lon")
            except:
                pass
        elif msg.type == "location":
            lat = msg.data.get("lat")
            lng = msg.data.get("lon")

    if lat is None or lng is None:
        await matcher.finish("无法获取位置信息，操作已取消。")

    try:
        api_params = {"LON": lng, "LAT": lat, "radius": radius}
        api_endpoint = f"{API_URL}/maihere/location/pic.php"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                api_endpoint,
                params=api_params
            )
            response.raise_for_status()
            data = response.json()

            if "map_url" in data:
                user_last_map_time[user_id] = current_time
                map_url = data["map_url"]
                note = data.get("note", "")
                await matcher.finish(f"{note}\n" + MessageSegment.image(file=map_url))
            else:
                error_msg = data.get("note", "地图生成失败，API未返回有效URL。")
                await matcher.finish(error_msg)

    except httpx.ReadTimeout:
        await matcher.finish("地图生成超时，请稍后再试。")
    except FinishedException:
        pass
    except Exception as e:
        await matcher.finish(f"生成机厅地图失败: {str(e)}")

@contribution_rank.handle()
async def handle_contribution_rank(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    group_id = event.group_id
    date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        stats = DataManager.load_report_stats()
        
        if date not in stats["daily_stats"] or str(group_id) not in stats["daily_stats"][date]:
            await matcher.finish("今日暂无上报数据，快去更新机厅人数吧！")
            return
            
        group_stats = stats["daily_stats"][date][str(group_id)]
        
        user_data = []
        for user_id, count in group_stats.items():
            nickname = stats["user_stats"].get(user_id, {}).get("nickname", "匿名用户").split("(")[0]
            user_data.append((nickname, int(count)))
        
        user_data.sort(key=lambda x: x[1], reverse=True)
        
        if not user_data:
            await matcher.finish("今日暂无上报数据。")
            return
            
        rank_text = f"【今日机厅上报榜】\n"
        for i, (nickname, count) in enumerate(user_data[:10]):
            # 前三名加个奖牌emoji
            prefix = f"{i+1}. "
            if i == 0: prefix = "🥇"
            elif i == 1: prefix = "🥈"
            elif i == 2: prefix = "🥉"
            
            rank_text += f"{prefix} {nickname}: {count}次\n"
            
        await matcher.send(rank_text.strip())
        
    except Exception as e:
        # 记录日志而不是直接吞掉异常
        print(f"贡献榜生成失败: {e}")
        await matcher.finish("生成贡献榜失败，请稍后再试。")