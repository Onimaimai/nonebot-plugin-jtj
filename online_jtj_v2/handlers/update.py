from nonebot import on_message
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, MessageEvent
from nonebot.matcher import Matcher
from datetime import datetime
import time

from ..state import group_subscriptions, global_aliases, silent_mode_config
from ..services.api_client import ApiClient
from ..services.data_manager import DataManager
from ..services.rate_limiter import RateLimiter
from ..utils.helpers import parse_update_command, get_status_symbol_by_source
from ..config.settings import DATA_DIR
from .core import send_forward_message

# 规则函数：检测消息是否以已订阅的简称开头
async def is_alias_command(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    
    text = event.get_plaintext().strip()
    
    # 检查消息是否以某个简称开头
    # 优化：可以先检查是否包含数字或特定后缀，减少遍历次数
    for alias in global_aliases.alias_to_ids.keys():
        if text.startswith(alias):
            return True
    
    return False

message_matcher = on_message(
    rule=Rule(is_alias_command),
    priority=100, 
    block=False
)

@message_matcher.handle()
async def handle_alias_commands(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    text = event.get_plaintext().strip()
    group_id = event.group_id
    
    # 1. 优先尝试最长匹配原则
    matched_alias = None
    # 将简称按长度降序排列，确保匹配最长的前缀
    sorted_aliases = sorted(global_aliases.alias_to_ids.keys(), key=len, reverse=True)
    
    for alias in sorted_aliases:
        if text.startswith(alias):
            # 检查剩余部分是否符合格式
            remaining = text[len(alias):].strip()
            # 可能的格式：
            # 1. 纯数字 (万达10)
            # 2. +/-数字 (万达+1)
            # 3. j/几 (万达j)
            # 4. 空 (如果是完全匹配简称，这里暂时不处理，除非有具体逻辑) 
            
            if remaining == 'j' or remaining == '几':
                matched_alias = alias
                break
            
            if parse_update_command(alias + remaining):
                matched_alias = alias
                break
            
            # 特殊情况处理：如果简称本身就是数字结尾，可能会被误判
            # 这里保持原逻辑：找到最长匹配的简称
            matched_alias = alias
            break

    if not matched_alias:
        # 尝试 "数字简称+数字" 的特殊回退逻辑 (如 7772 -> 777 + 2)
        if text.isdigit() and len(text) >= 2:
            for alias_len in range(len(text) - 1, 0, -1):
                alias_candidate = text[:alias_len]
                remaining = text[alias_len:]
                
                if alias_candidate in global_aliases.alias_to_ids and remaining.isdigit():
                    update_parsed = (alias_candidate, int(remaining), "set")
                    await handle_update(bot, event, matcher, update_parsed)
                    return
        return
    
    remaining = text[len(matched_alias):].strip()
    
    # 1. 处理查询指令：简称j
    if remaining == 'j' or remaining == '几':
        shop_ids = global_aliases.alias_to_ids.get(matched_alias, [])
        if not shop_ids:
            return
        
        subs = group_subscriptions[group_id]
        subscribed_shop_ids = [shop_id for shop_id in shop_ids if shop_id in subs.shops]
        
        if not subscribed_shop_ids:
            # 本群未订阅
            return
            
        messages = []
        should_send = group_id not in silent_mode_config.silent_groups or event.is_tome()
        
        for shop_id in subscribed_shop_ids:
            shop_info = subs.shops[shop_id]
            shop_data = await ApiClient.get_shop_by_id(shop_id)
            if not shop_data:
                continue
            
            shop_info.last_number = int(shop_data.get("shop_number", 0))
            status_symbol = get_status_symbol_by_source(shop_data.get("shop_source", ""))
            shop_name = shop_data.get('shop_name', f'机厅{shop_id}')
            source = shop_data.get('shop_source', '未知')
            
            messages.append(
                f"{shop_name}({shop_id})\n"
                f"当前：{shop_info.last_number} 人 {status_symbol}\n"
                f"来源：{source}"
            )
        
        # 即使只查询，也保存一下可能的更新（比如last_number同步了）
        DataManager.save_subscriptions(group_subscriptions)
        
        if messages and should_send:
            await matcher.send("\n\n".join(messages))
        return
    
    # 2. 处理更新指令
    update_parsed = parse_update_command(matched_alias + remaining)
    if update_parsed:
        await handle_update(bot, event, matcher, update_parsed)
        return

async def handle_update(bot: Bot, event: GroupMessageEvent, matcher: Matcher, parsed: tuple):
    alias, number_change, op_type = parsed
    group_id = event.group_id
    user_id = event.get_user_id()
    
    # 速率限制
    allowed, reason = RateLimiter.check_rate_limit(group_id, user_id)
    if not allowed:
        await matcher.finish(reason, reply_message=True)
    
    shop_ids = global_aliases.alias_to_ids.get(alias, [])
    if not shop_ids:
        return
    
    subs = group_subscriptions[group_id]
    subscribed_shop_ids = [shop_id for shop_id in shop_ids if shop_id in subs.shops]
    
    if not subscribed_shop_ids:
        # 本群未订阅该机厅，不响应
        return
    
    # 默认更新第一个匹配的订阅机厅
    target_shop_id = subscribed_shop_ids[0]
    
    # 获取用户信息用于来源标记
    try:
        user_info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
        user_nickname = user_info.get('nickname', '') or user_info.get('card', '') 
        if not user_nickname:
             user_nickname = f"用户{user_id}"
    except:
        user_nickname = f"用户{user_id}"

    user_str = f"{user_nickname}({user_id})"
    timestamp = datetime.now().strftime("%H:%M:%S")
    source = f"{user_str} \n时间：{timestamp}"
    
    shop_info = subs.shops[target_shop_id]
    
    if op_type == "set":
        new_number = number_change
    else:
        new_number = shop_info.last_number + number_change
        new_number = max(0, new_number)
    
    if new_number > 50:
        await matcher.finish("人数超过50？禁止恶意上报！", reply_message=True)
        
    shop_data = await ApiClient.get_shop_by_id(target_shop_id)
    shop_name = shop_data.get("shop_name", f"机厅{target_shop_id}") if shop_data else f"机厅{target_shop_id}"
    
    # 构建回复消息
    if op_type == "add":
        action_str = f"增加 {number_change} 人"
    elif op_type == "subtract":
        action_str = f"减少 {abs(number_change)} 人"
    else:
        action_str = f"设置为 {new_number} 人"

    message = (
        f"✅ 更新成功！\n"  
        f"{shop_name}\n"  
        f"当前：{new_number} 人"
    )
    
    if group_id not in silent_mode_config.silent_groups or event.is_tome():
        await matcher.send(message)
    
    # 异步更新API
    success = await ApiClient.update_shop_number(target_shop_id, new_number, source)
    if not success:
        # 如果API更新失败，是否需要提示？通常静默失败或者记日志
        print(f"Failed to update shop {target_shop_id} number via API.")

    shop_info.last_number = new_number
    
    # 更新统计
    await update_stats(group_id, user_id, user_nickname)
    
    DataManager.save_subscriptions(group_subscriptions)

async def update_stats(group_id: int, user_id: str, user_nickname: str):
    today = datetime.now().strftime("%Y-%m-%d")
    stats = DataManager.load_report_stats()
    
    if today not in stats["daily_stats"]:
        stats["daily_stats"][today] = {}
    
    if str(group_id) not in stats["daily_stats"][today]:
        stats["daily_stats"][today][str(group_id)] = {}
    
    if user_id not in stats["daily_stats"][today][str(group_id)]:
        stats["daily_stats"][today][str(group_id)][user_id] = 0
    
    stats["daily_stats"][today][str(group_id)][user_id] += 1
    
    if user_id not in stats["user_stats"]:
        stats["user_stats"][user_id] = {
            "total": 0,
            "nickname": user_nickname
        }
    else:
        # 更新昵称
        stats["user_stats"][user_id]["nickname"] = user_nickname
    
    stats["user_stats"][user_id]["total"] += 1
    stats["last_update"] = time.time()
    
    DataManager.save_report_stats(stats)