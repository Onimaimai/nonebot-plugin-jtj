from nonebot import on_command
from nonebot.adapters import Message
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot
from nonebot.matcher import Matcher

from ..state import group_subscriptions, global_aliases
from ..services.api_client import ApiClient
from ..services.data_manager import DataManager
from ..models.schemas import ShopInfo

subscribe = on_command("订阅机厅", priority=10, block=True)
unsubscribe = on_command("退订机厅", priority=10, block=True)
subscribe_city = on_command("订阅城市", priority=10, block=True)
unsubscribe_city = on_command("退订城市", aliases={"取消订阅城市"}, priority=10, block=True)
add_alias = on_command("添加简称", priority=10, block=True)
remove_alias = on_command("删除简称", priority=10, block=True)
list_aliases = on_command("查看简称", priority=10, block=True)

@subscribe.handle()
async def handle_subscribe(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要订阅的机厅ID，多个ID用空格分隔。")
    
    try:
        # 兼容中文逗号等分隔符
        cleaned_args = args_str.replace("，", " ").replace(",", " ")
        shop_ids = [int(id_str) for id_str in cleaned_args.split()]
    except ValueError:
        await matcher.finish("机厅ID必须是数字，多个ID用空格分隔。")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    results = []
    has_changes = False
    
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
        
    await matcher.finish("\n".join(results))

@unsubscribe.handle()
async def handle_unsubscribe(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要取消订阅的机厅ID，多个ID用空格分隔。")
    
    try:
        cleaned_args = args_str.replace("，", " ").replace(",", " ")
        shop_ids = [int(id_str) for id_str in cleaned_args.split()]
    except ValueError:
        await matcher.finish("机厅ID必须是数字，多个ID用空格分隔。")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    results = []
    has_changes = False
    
    for shop_id in shop_ids:
        # 即使机厅不存在API中，只要在订阅列表中就可以退订
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
    await matcher.finish("\n".join(results))

@subscribe_city.handle()
async def handle_subscribe_city(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    city_name = args.extract_plain_text().strip()
    if not city_name:
        await matcher.finish("请输入要订阅的城市名称。")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    await matcher.send(f"正在获取 {city_name} 的机厅信息，请稍候...")
    shop_data = await ApiClient.get_city_shops(city_name)
    if not shop_data:
        await matcher.finish(f"没有查到 {city_name} 的机厅信息，请检查城市名称是否正确。")
    
    results = []
    new_subscriptions = 0
    already_subscribed = 0
    
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
    
    if new_subscriptions == 0:
        if already_subscribed > 0:
            await matcher.finish(f"已订阅 {city_name} 的所有机厅，共 {already_subscribed} 个。")
        else:
            await matcher.finish(f"未能订阅 {city_name} 的任何机厅。")
    else:
        summary = f"成功订阅 {city_name} 的 {new_subscriptions} 个机厅"
        if already_subscribed > 0:
            summary += f"，已有 {already_subscribed} 个机厅被订阅"
        
        # 结果列表可能很长，只显示前10个或者不显示详细列表，避免刷屏
        if len(results) > 10:
             await matcher.finish(f"{summary}。\n包括：{', '.join(results[:10])} 等。")
        else:
             await matcher.finish(f"{summary}：\n" + "\n".join(results))

@unsubscribe_city.handle()
async def handle_unsubscribe_city(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    city_name = args.extract_plain_text().strip()
    if not city_name:
        await matcher.finish("请输入要取消订阅的城市名称。")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    await matcher.send(f"正在获取 {city_name} 的机厅信息，请稍候...")
    shop_data = await ApiClient.get_city_shops(city_name)
    if not shop_data:
        await matcher.finish(f"没有查到 {city_name} 的机厅信息。")
    
    results = []
    unsubscribed = 0
    not_subscribed = 0
    
    for shop in shop_data:
        if not isinstance(shop, dict) or "id" not in shop:
            continue
        
        shop_id = shop["id"]
        shop_name = shop.get("shop_name", f"机厅{shop_id}")
        
        if shop_id not in subs.shops:
            not_subscribed += 1
            continue
        
        subs.shops.pop(shop_id)
        unsubscribed += 1
        results.append(f"{shop_name}")
    
    if unsubscribed > 0:
        DataManager.save_subscriptions(group_subscriptions)
    
    if unsubscribed == 0:
        if not_subscribed > 0:
            await matcher.finish(f"本群未订阅 {city_name} 的任何机厅。")
        else:
            await matcher.finish(f"未能取消订阅 {city_name} 的任何机厅。")
    else:
        summary = f"成功取消订阅 {city_name} 的 {unsubscribed} 个机厅"
        
        if len(results) > 10:
             await matcher.finish(f"{summary}。")
        else:
             await matcher.finish(f"{summary}：\n" + ", ".join(results))

@add_alias.handle()
async def handle_add_alias(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要添加简称的机厅ID和简称，例如：添加简称 33 f")
    
    parts = args_str.split(maxsplit=1)
    if len(parts) < 2:
        await matcher.finish("格式错误。正确格式：添加简称 <机厅ID> <简称>")
    
    shop_id_str, alias = parts
    if not shop_id_str.isdigit():
        await matcher.finish("机厅ID必须是数字。")
    
    group_id = event.group_id
    shop_id = int(shop_id_str)
    subs = group_subscriptions[group_id]
    
    if shop_id not in subs.shops:
        await matcher.finish(f"未订阅ID为 {shop_id} 的机厅，请先订阅后再设置简称。")
        
    if alias not in global_aliases.alias_to_ids:
        global_aliases.alias_to_ids[alias] = []
    
    if shop_id in global_aliases.alias_to_ids[alias]:
        await matcher.finish(f"机厅 {shop_id} 已经有简称: {alias}")
        
    global_aliases.alias_to_ids[alias].append(shop_id)
    
    DataManager.save_global_aliases(global_aliases)
    
    shop_data = await ApiClient.get_shop_by_id(shop_id)
    shop_name = shop_data.get('shop_name') if shop_data else f"机厅{shop_id}"
    
    await matcher.finish(f"✅ 已为 {shop_name}({shop_id}) 添加简称: {alias}")

@remove_alias.handle()
async def handle_remove_alias(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要删除简称的机厅ID和简称，例如：删除简称 33 f")
    
    parts = args_str.split(maxsplit=1)
    if len(parts) < 2:
        await matcher.finish("格式错误。正确格式：删除简称 <机厅ID> <简称>")
    
    shop_id_str, alias = parts
    if not shop_id_str.isdigit():
        await matcher.finish("机厅ID必须是数字。")
    
    shop_id = int(shop_id_str)
    
    if shop_id not in global_aliases.alias_to_ids.get(alias, []):
        await matcher.finish(f"机厅 {shop_id} 没有简称: {alias}")
        
    if alias in global_aliases.alias_to_ids and shop_id in global_aliases.alias_to_ids[alias]:
        global_aliases.alias_to_ids[alias].remove(shop_id)
        # 如果该简称没有关联任何机厅，则删除该简称
        if not global_aliases.alias_to_ids[alias]:
            global_aliases.alias_to_ids.pop(alias)
        
    DataManager.save_global_aliases(global_aliases)
    
    await matcher.finish(f"🗑️ 已删除机厅 {shop_id} 的简称: {alias}")

@list_aliases.handle()
async def handle_list_aliases(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    if args_str:
        # 查看指定机厅的简称
        if not args_str.isdigit():
            await matcher.finish("机厅ID必须是数字。")
        
        shop_id = int(args_str)
        # 即使未订阅也允许查看简称，或者限制为订阅？原逻辑限制为订阅
        if shop_id not in subs.shops:
            await matcher.finish(f"未订阅ID为 {shop_id} 的机厅，无法查看其简称。")
        
        shop_aliases = []
        for alias, shop_ids in global_aliases.alias_to_ids.items():
            if shop_id in shop_ids:
                shop_aliases.append(alias)
        
        shop_data = await ApiClient.get_shop_by_id(shop_id)
        shop_name = shop_data['shop_name'] if shop_data else "未知机厅"
        
        if not shop_aliases:
            await matcher.finish(f"{shop_name}({shop_id}) 没有设置简称。")
        
        await matcher.finish(f"{shop_name}({shop_id}) 的简称:\n" + "\n".join(shop_aliases))
    else:
        # 查看所有简称
        if not subs.shops:
            await matcher.finish("本群尚未订阅任何机厅。")
        
        subscribed_shop_ids = set(subs.shops.keys())
        messages = []
        
        # 优化显示逻辑，按简称分组
        for alias, shop_ids in global_aliases.alias_to_ids.items():
            group_shop_ids = [sid for sid in shop_ids if sid in subscribed_shop_ids]
            if group_shop_ids:
                # 获取第一个机厅的信息作为示例，或者只显示ID
                # 为了防止API请求过多，这里只显示ID，或者如果缓存有名字就显示名字
                shop_names = []
                for sid in group_shop_ids:
                    # 尝试从缓存获取名字，不发起网络请求
                    # 注意：这里需要直接访问缓存，不能用ApiClient.get_shop_by_id因为那是async的且可能请求网络
                    # 简单起见，只显示ID
                    shop_names.append(str(sid))
                
                messages.append(f"• {alias}: {', '.join(shop_names)}")
        
        if not messages:
            await matcher.finish("本群订阅的机厅均未设置简称。")
        
        # 分页或者限制长度
        await matcher.finish("本群机厅简称列表:\n" + "\n".join(messages))