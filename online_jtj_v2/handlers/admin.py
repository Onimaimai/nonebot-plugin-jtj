from nonebot import on_command
from nonebot.adapters import Message
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, MessageEvent
from nonebot.matcher import Matcher
from nonebot.exception import FinishedException
from nonebot.rule import to_me
from datetime import datetime
import json
import time
import re
import httpx

from ..state import review_cache, silent_mode_config
from ..services.api_client import ApiClient
from ..services.data_manager import DataManager
from ..config.settings import SUPER_USER_ID, SUPER_USER_ID2, API_URL, API_KEY

apply_shop = on_command("申请机厅", priority=10, block=True)
add_shop_location = on_command("添加机厅", aliases={"新建机厅"}, priority=10, block=True)
review_shop = on_command("审核机厅", priority=10, block=True)
clear_review_shop = on_command("清空审核机厅", priority=10, block=True)
silent_mode = on_command("机厅静默", aliases={"jt静默"}, priority=10, block=True, rule=to_me())

@silent_mode.handle()
async def handle_silent_mode(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    group_id = event.group_id
    arg = args.extract_plain_text().strip()
    
    if not arg:
        is_silent = group_id in silent_mode_config.silent_groups
        await matcher.finish(f"当前群组静默模式：{'开启' if is_silent else '关闭'}")
    
    if arg in ["开", "开启", "on", "1"]:
        if group_id in silent_mode_config.silent_groups:
            await matcher.finish("静默模式已经开启")
        silent_mode_config.silent_groups.add(group_id)
        DataManager.save_silent_mode(silent_mode_config)
        await matcher.finish("已开启静默模式，机器人将不再主动回复人数消息，但可通过@机器人进行查询。")
    
    elif arg in ["关", "关闭", "off", "0"]:
        if group_id not in silent_mode_config.silent_groups:
            await matcher.finish("静默模式已经关闭")
        silent_mode_config.silent_groups.remove(group_id)
        DataManager.save_silent_mode(silent_mode_config)
        await matcher.finish("已关闭静默模式，机器人将正常回复人数消息")
    
    else:
        await matcher.finish("参数错误，请使用：开启/关闭")

@apply_shop.handle()
async def handle_apply_shop(bot: Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入机厅名称和所在城市，例如：申请机厅 新机厅 杭州")
    
    parts = args_str.split(maxsplit=1)
    if len(parts) < 2:
        await matcher.finish("请输入机厅名称和所在城市，例如：申请机厅 新机厅 杭州")
    
    shop_name, city = parts
    user_id = event.get_user_id()
    
    if isinstance(event, GroupMessageEvent):
        user_info = await bot.get_group_member_info(group_id=event.group_id, user_id=user_id)
        user_nickname = user_info.get('nickname', '') + "(" + user_id + ")"
        group_id = event.group_id
        
        apply_info = (
            f"收到新的机厅申请（群聊）：\n"
            f"机厅名称：{shop_name}\n"
            f"所在城市：{city}\n"
            f"申请者：{user_nickname}\n"
            f"申请群组：{group_id}"
        )
    else:
        user_info = await bot.get_stranger_info(user_id=user_id)
        user_nickname = user_info.get('nickname', '') + "(" + user_id + ")"
        
        apply_info = (
            f"收到新的机厅申请（私聊）：\n"
            f"机厅名称：{shop_name}\n"
            f"所在城市：{city}\n"
            f"申请者：{user_nickname}"
        )
    
    await bot.send_private_msg(user_id=SUPER_USER_ID, message=apply_info)
    await bot.send_private_msg(user_id=SUPER_USER_ID2, message=apply_info)
    await matcher.finish("成功提交机厅申请，请等待审核", reply_message=True)

@add_shop_location.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    await matcher.send(f"请发送QQ位置")

@add_shop_location.got("location")
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    lat = None
    lng = None
    shop_name = None
    shop_address = None
    city_name = None
    city_id = None
    
    for msg in event.message:
        if msg.type == "json":
            try:
                data = json.loads(msg.data['data'])
                if 'meta' in data and 'Location.Search' in data['meta']:
                    loc = data['meta']['Location.Search']
                    lat = loc.get("lat")
                    lng = loc.get("lng") or loc.get("lon")
                    shop_name = loc.get("name", "")
                    shop_address = loc.get("address", "")
                elif 'meta' in data and 'location' in data['meta']:
                    loc = data['meta']['location']
                    lat = loc.get("lat")
                    lng = loc.get("lng") or loc.get("lon")
                    shop_name = loc.get("name", "")
                    shop_address = loc.get("address", "")
            except Exception as e:
                await matcher.finish(f"解析位置消息失败: {e}")
        elif msg.type == "location":
            lat = msg.data.get("lat")
            lng = msg.data.get("lon")
            shop_name = msg.data.get("name", "")
            shop_address = msg.data.get("content", "")

    city_match = re.search(r"(?:[\u4e00-\u9fa5]+省)?([\u4e00-\u9fa5]{2,4})市", shop_address or "")
    if city_match:
        city_name = city_match.group(1)
    else:
        await matcher.finish("未能从地址中识别出城市名，请手动联系管理员添加。")

    city_shops = await ApiClient.get_city_shops(city_name)
    if not city_shops or not isinstance(city_shops, list):
        await matcher.finish(f"未能获取城市 {city_name} 的机厅信息，无法添加。")
    
    for shop in city_shops:
        if isinstance(shop, dict) and ("city_id" in shop or "id" in shop):
            city_id = shop.get("city_id") or shop.get("id")
            break
    if not city_id:
        await matcher.finish(f"未能获取城市 {city_name} 的ID，无法添加。")

    api_url = f"{API_URL}/maihere/location/add.php"
    params = {
        "shop_name": str(shop_name),
        "shop_address": str(shop_address),
        "shop_city": str(city_id),
        "key": API_KEY,
        "LON": str(lng),
        "LAT": str(lat),
        "coin": "1"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, params=params)
            data = resp.json()
            if "success" in data:
                review_msg = f"收到机厅申请！\n店名：{shop_name}\n地址：{shop_address}\n城市：{city_name}\n请发送 审核机厅 处理！"
                await bot.send_private_msg(user_id=SUPER_USER_ID, message=review_msg)
                await bot.send_private_msg(user_id=SUPER_USER_ID2, message=review_msg)
                await matcher.finish(f"添加机厅成功：请等待审核！")
            elif "error" in data:
                await matcher.finish(f"添加机厅失败：{data['error']}")
            else:
                await matcher.finish(f"添加机厅失败，未知返回：{data}")
    except FinishedException:
        pass
    except Exception as e:
        # API调用失败时，使用本地缓存
        try:
            new_shop = {
                "id": int(time.time()),
                "shop_name": shop_name,
                "shop_address": shop_address,
                "shop_city": city_id,
                "LON": lng,
                "LAT": lat,
                "coin": "1",
                "add_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            review_cache.pending_shops.append(new_shop)
            review_cache.last_update = time.time()
            DataManager.save_review_cache(review_cache)
            
            review_msg = f"收到机厅申请（本地缓存）！\n店名：{shop_name}\n地址：{shop_address}\n城市：{city_name}\n请发送 审核机厅 处理！"
            await bot.send_private_msg(user_id=SUPER_USER_ID, message=review_msg)
            await bot.send_private_msg(user_id=SUPER_USER_ID2, message=review_msg)
            await matcher.finish(f"添加机厅成功（本地缓存）：请等待审核！")
        except Exception as cache_error:
            await matcher.finish(f"添加机厅失败：{cache_error}")

@review_shop.handle()
async def _(bot: Bot, event: MessageEvent, matcher: Matcher):
    user_id = str(event.get_user_id())
    if user_id not in [SUPER_USER_ID, SUPER_USER_ID2]:
        await matcher.finish("无权限操作，仅超级用户可用。")
    
    api_url = f"{API_URL}/maihere/location/pass.php"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url)
            data = resp.json()
            if not data or (isinstance(data, dict) and not data.get("data")):
                # 尝试本地缓存
                raise Exception("API无数据")
            
            review_list = data.get("data") if isinstance(data, dict) else data
            if not review_list:
                raise Exception("API无数据")
            
            msg = ["待审核机厅列表："]
            for shop in review_list:
                msg.append(f"ID: {shop.get('id')}\n店名: {shop.get('shop_name')}\n地址: {shop.get('shop_address')}\n")
            await matcher.finish("\n".join(msg) + "\n请发送通过审核的机厅ID（数字）")
            
    except FinishedException:
        pass
    except Exception as e:
        if not review_cache.pending_shops:
            await matcher.finish("暂无待审核机厅。")
        
        msg = ["待审核机厅列表（本地缓存）："]
        for shop in review_cache.pending_shops:
            msg.append(f"ID: {shop.get('id')}\n店名: {shop.get('shop_name')}\n地址: {shop.get('shop_address')}\n")
        await matcher.finish("\n".join(msg) + "\n请发送通过审核的机厅ID（数字）")

@review_shop.got("wait_review_id")
async def _(bot: Bot, event: MessageEvent, matcher: Matcher):
    user_id = str(event.get_user_id())
    if user_id not in [SUPER_USER_ID, SUPER_USER_ID2]:
        await matcher.finish("无权限操作，仅超级用户可用。")
    shop_id = event.get_plaintext().strip()
    if not shop_id.isdigit():
        await matcher.finish("机厅ID错误，操作已取消")
    
    api_url = f"{API_URL}/maihere/location/pass.php"
    params = {"pass": shop_id, "key": API_KEY}
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, params=params)
            data = resp.json()
            if "success" in data:
                await matcher.finish(f"机厅ID {shop_id} 审核通过成功！")
            elif "error" in data:
                await matcher.finish(f"审核失败：{data['error']}")
            else:
                await matcher.finish(f"审核失败，未知返回：{data}")
    except FinishedException:
        pass
    except Exception as e:
        try:
            shop_id_int = int(shop_id)
            found_shop = None
            for i, shop in enumerate(review_cache.pending_shops):
                if shop.get('id') == shop_id_int:
                    found_shop = review_cache.pending_shops.pop(i)
                    break
            
            if found_shop:
                review_cache.last_update = time.time()
                DataManager.save_review_cache(review_cache)
                await matcher.finish(f"机厅ID {shop_id} 审核通过成功（本地缓存）！")
            else:
                await matcher.finish(f"未找到ID为 {shop_id} 的待审核机厅")
        except Exception as cache_error:
            await matcher.finish(f"审核失败：{cache_error}")

@clear_review_shop.handle()
async def _(bot: Bot, event: MessageEvent, matcher: Matcher):
    user_id = str(event.get_user_id())
    if user_id not in [SUPER_USER_ID, SUPER_USER_ID2]:
        await matcher.finish("无权限操作，仅超级用户可用。")
    
    api_url = f"{API_URL}/maihere/location/clear_review.php"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url)
            if "成功修改了" in resp.text or "success" in resp.text.lower():
                await matcher.finish("清空审核机厅列表成功！")
            else:
                await matcher.finish(f"清空审核机厅失败：{resp.text}")
    except FinishedException:
        pass
    except Exception as e:
        await matcher.finish(f"清空审核机厅接口请求失败：{e}")
