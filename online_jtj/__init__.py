import json
import os
from pathlib import Path
from nonebot import on_command, on_message, get_driver
from nonebot.rule import Rule
from nonebot.adapters import Message
from nonebot.params import CommandArg, Event
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, Bot, Event
from nonebot.matcher import Matcher
import httpx
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import re
import time
from datetime import datetime
import asyncio

# 数据存储路径
DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "subscriptions.json"
CACHE_FILE = DATA_DIR / "shop_cache.json"
ALIAS_FILE = DATA_DIR / "aliases.json"

def dataclass_from_dict(cls, data):
    return cls(**data)

__plugin_meta__ = PluginMetadata(
    name="机厅查询",
    description="查询和更新maimai机厅人数，支持简称和多种更新方式",
    usage="""指令：
    jtj <城市> - 查询城市所有机厅
    jtj - 查询本群订阅的机厅
    订阅机厅 <id1> [id2]... - 订阅多个机厅(空格分隔)
    取消订阅 <id1> [id2]... - 取消订阅多个机厅(空格分隔)
    订阅城市 <城市> - 订阅指定城市的所有机厅
    取消订阅城市 <城市> - 取消订阅指定城市的所有机厅
    申请机厅 <店名+添加/删除> <城市> - 申请添加或删除机厅
    添加简称 <id> <简称> - 为机厅添加简称
    删除简称 <id> <简称> - 删除机厅的简称
    查看简称 [id] - 查看所有简称或指定机厅的简称
    <简称><数字> - 直接更新人数(如:万达10)
    <简称>+<数字> - 增加人数(如:万达+2)
    <简称>-<数字> - 减少人数(如:万达-1)
    """,
)

# 配置项
API_KEY = "xxx"  # 替换为实际的API key
SUPER_USER_ID = "123"  # 超级用户ID

@dataclass
class ShopInfo:
    id: int
    last_number: int = 0

    def to_dict(self):
        return {
            "id": self.id,
            "last_number": self.last_number
        }

@dataclass
class GroupSubscriptions:
    shops: Dict[int, ShopInfo] = field(default_factory=dict)

    def to_dict(self):
        return {
            "shops": {str(k): v.to_dict() for k, v in self.shops.items()}
        }

# 机厅缓存数据类
@dataclass
class ShopCache:
    shop_data: Dict[int, dict] = field(default_factory=dict)  # 机厅ID -> 机厅信息
    city_shops: Dict[str, List[dict]] = field(default_factory=dict)  # 城市名 -> 机厅列表
    last_update: Dict[str, float] = field(default_factory=dict)  # 记录最后更新时间
    
    def to_dict(self):
        return {
            "shop_data": {str(k): v for k, v in self.shop_data.items()},
            "city_shops": self.city_shops,
            "last_update": self.last_update
        }
    
    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        
        shop_data = {int(k): v for k, v in data.get("shop_data", {}).items()}
        city_shops = data.get("city_shops", {})
        last_update = data.get("last_update", {})
        
        return cls(
            shop_data=shop_data,
            city_shops=city_shops,
            last_update=last_update
        )

# 全局简称数据类
@dataclass
class GlobalAliases:
    alias_to_ids: Dict[str, List[int]] = field(default_factory=dict)  # 简称 -> 机厅ID列表
    
    def to_dict(self):
        return {
            "alias_to_ids": self.alias_to_ids
        }
    
    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        
        return cls(
            alias_to_ids=data.get("alias_to_ids", {})
        )

# 初始化数据存储目录
os.makedirs(DATA_DIR, exist_ok=True)

def load_data() -> Dict[int, GroupSubscriptions]:
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

def save_data(data: Dict[int, GroupSubscriptions]):
    try:
        serializable_data = {
            str(group_id): group_subs.to_dict()
            for group_id, group_subs in data.items()
        }
        
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存数据失败: {str(e)}")

# 加载机厅缓存数据
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

# 保存机厅缓存数据
def save_shop_cache(cache: ShopCache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache.to_dict(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存机厅缓存失败: {str(e)}")

# 加载全局简称数据
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

# 保存全局简称数据
def save_global_aliases(aliases: GlobalAliases):
    try:
        with open(ALIAS_FILE, "w", encoding="utf-8") as f:
            json.dump(aliases.to_dict(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存全局简称失败: {str(e)}")

# 初始化数据
group_subscriptions = load_data()
shop_cache = load_shop_cache()
global_aliases = load_global_aliases()

# 指令处理器
jtj = on_command("jtj", aliases={"查询机厅"}, priority=10, block=True)
subscribe = on_command("订阅机厅", priority=10, block=True)
unsubscribe = on_command("取消订阅", priority=10, block=True)
subscribe_city = on_command("订阅城市", priority=10, block=True)
unsubscribe_city = on_command("取消订阅城市", priority=10, block=True)
add_alias = on_command("添加简称", priority=10, block=True)
remove_alias = on_command("删除简称", priority=10, block=True)
list_aliases = on_command("查看简称", priority=10, block=True)
apply_shop = on_command("申请机厅", priority=10, block=True)

# 规则函数：检测消息是否以已订阅的简称开头
async def is_alias_command(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    
    text = event.get_plaintext().strip()
    
    # 检查消息是否以某个简称开头
    for alias in global_aliases.alias_to_ids.keys():
        if text.startswith(alias):
            return True
    
    return False
  
# 修改为使用规则的消息处理器
message_matcher = on_message(
    rule=Rule(is_alias_command),  # 使用自定义规则
    priority=100, 
    block=False
)

@message_matcher.handle()
async def handle_alias_commands(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    text = event.get_plaintext().strip()
    group_id = event.group_id
    
    # 找出匹配的最长简称（避免短简称误匹配）
    matched_alias = None
    for alias in sorted(global_aliases.alias_to_ids.keys(), key=len, reverse=True):
        if text.startswith(alias):
            matched_alias = alias
            break
    
    if not matched_alias:
        return
    
    # 获取剩余部分（去掉简称后的内容）
    remaining = text[len(matched_alias):].strip()
    
    # 1. 处理查询指令：简称j
    if remaining == 'j' or remaining == '几':
        await handle_alias_query(event, matcher, matched_alias)
        return
    
    # 2. 处理更新指令：简称+数字/简称-数字/简称数字
    update_parsed = parse_update_command(matched_alias + remaining)
    if update_parsed:
        await handle_update(bot, event, matcher, update_parsed)
        return
      
async def handle_alias_query(event: GroupMessageEvent, matcher: Matcher, alias: str):
    """处理简称查询"""
    group_id = event.group_id
    
    # 获取所有使用该简称的机厅ID
    shop_ids = global_aliases.alias_to_ids.get(alias, [])
    if not shop_ids:
        #await matcher.finish(f"简称'{alias}'未关联任何机厅")
        return
    
    # 检查群组是否订阅了这些机厅
    subs = group_subscriptions[group_id]
    subscribed_shop_ids = [shop_id for shop_id in shop_ids if shop_id in subs.shops]
    
    if not subscribed_shop_ids:
        #await matcher.finish(f"本群未订阅使用简称'{alias}'的机厅")
        return
    
    # 获取所有机厅信息
    messages = []
    for shop_id in subscribed_shop_ids:
        shop_info = subs.shops[shop_id]
        shop_data = await get_shop_by_id(shop_id)
        
        if not shop_data:
            messages.append(f"机厅{shop_id}: 获取信息失败")
            continue
        
        # 更新本地记录的最后人数
        shop_info.last_number = int(shop_data.get("shop_number", 0))
        
        predicted = shop_data.get("predicted_number", "无预测数据")
        messages.append(
            f"{shop_data['shop_name']}({shop_id})\n"
            f"当前：{shop_info.last_number} 人\n"
            f"来源：{shop_data['shop_source']}"
        )
    
    save_data(group_subscriptions)
    await matcher.send("\n\n".join(messages))

async def handle_update(bot: Bot, event: GroupMessageEvent, matcher: Matcher, parsed: Tuple[str, int, str]):
    """处理人数更新"""
    alias, number_change, op_type = parsed
    group_id = event.group_id
    
    # 获取所有使用该简称的机厅ID
    shop_ids = global_aliases.alias_to_ids.get(alias, [])
    if not shop_ids:
        #await matcher.finish(f"简称'{alias}'未关联任何机厅")
        return
    
    # 检查群组是否订阅了这些机厅
    subs = group_subscriptions[group_id]
    subscribed_shop_ids = [shop_id for shop_id in shop_ids if shop_id in subs.shops]
    
    if not subscribed_shop_ids:
        #await matcher.finish(f"本群未订阅使用简称'{alias}'的机厅")
        return
    
    # 只取排序靠前的机厅ID
    target_shop_id = subscribed_shop_ids[0]
    
    # 上报来源信息
    user_id = event.get_user_id()
    user_info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
    user_nickname = user_info.get('nickname', '') + "(" + user_id + ")"
    timestamp = datetime.now().strftime("%H:%M:%S")
    source = f"{user_nickname} \n时间：{timestamp}"
    
    # 更新机厅人数
    shop_info = subs.shops[target_shop_id]
    
    # 计算新人数
    if op_type == "set":
        new_number = number_change
    else:  # add or subtract
        new_number = shop_info.last_number + number_change
        new_number = max(0, new_number)
    
    if new_number >30:
        await matcher.finish("禁止恶意上报！",reply_message=True)
        
    shop_name = (await get_shop_by_id(target_shop_id) or {}).get("shop_name", f"机厅{target_shop_id}")
    message = (
        f"更新成功！\n"  
        f"{shop_name}\n"  
        f"当前：{new_number} 人"
    )
    await matcher.send(message)
    
    # 更新API
    success = await update_shop_number(target_shop_id, new_number, source)
    shop_info.last_number = new_number
    
    # 保存更新后的数据
    save_data(group_subscriptions) 


async def get_shop_by_id(shop_id: int) -> Optional[dict]:
    """根据机厅ID获取单个机厅信息"""
    # 先检查缓存
    if shop_id in shop_cache.shop_data:
        # 检查缓存是否过期
        last_update = shop_cache.last_update.get(f"shop_{shop_id}", 0)
        if time.time() - last_update < 3600:  # 缓存有效期
            return shop_cache.shop_data[shop_id]
    
    # 缓存不存在或已过期，从API获取
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.wenuu.cn/maimai-report/Data/getData_solo.php",
                params={"id": shop_id},
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, dict):
                # 更新缓存
                shop_cache.shop_data[shop_id] = data
                shop_cache.last_update[f"shop_{shop_id}"] = time.time()
                save_shop_cache(shop_cache)
                return data
            
            return None
    except Exception as e:
        print(f"获取机厅信息失败: {str(e)}")
        return None

async def update_shop_number(shop_id: int, number: int, source: str) -> bool:
    """更新机厅人数"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.wenuu.cn/maimai-report/Data/uploadData.php",
                params={
                    "id": shop_id,
                    "number": number,
                    "source": source,
                    "key": API_KEY
                },
                timeout=10.0
            )
            response.raise_for_status()
            
            # 如果更新成功，同时更新缓存
            if response.text.strip() == "数据更新成功":
                if shop_id in shop_cache.shop_data:
                    shop_cache.shop_data[shop_id]["shop_number"] = number
                    shop_cache.shop_data[shop_id]["shop_source"] = source
                    shop_cache.last_update[f"shop_{shop_id}"] = time.time()
                    save_shop_cache(shop_cache)
                return True
            return False
    except Exception as e:
        print(f"更新机厅人数失败: {str(e)}")
        # 接口失效时，只更新本地缓存
        if shop_id in shop_cache.shop_data:
            shop_cache.shop_data[shop_id]["shop_number"] = number
            shop_cache.shop_data[shop_id]["shop_source"] = source
            shop_cache.last_update[f"shop_{shop_id}"] = time.time()
            save_shop_cache(shop_cache)
            return True
        return False
      
def parse_update_command(text: str) -> Optional[Tuple[str, int, str]]:
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

async def get_city_shops(city_name: str) -> Optional[List[dict]]:
    """根据城市名获取该城市所有机厅信息"""
    # 先检查缓存
    if city_name in shop_cache.city_shops:
        # 检查缓存是否过期（超过1小时）
        last_update = shop_cache.last_update.get(f"city_{city_name}", 0)
        if time.time() - last_update < 3600:  # 1小时内的缓存有效
            return shop_cache.city_shops[city_name]
    
    # 缓存不存在或已过期，从API获取
    try:
        async with httpx.AsyncClient() as client:
            city_response = await client.get(
                "https://api.wenuu.cn/maimai-report/Query/queryCity.php",
                params={"name": city_name},
                timeout=10.0
            )
            city_response.raise_for_status()
            city_data = city_response.json()
            
            if not city_data:
                return None
            
            # 检查城市数据格式
            if not isinstance(city_data, list) or len(city_data) == 0:
                print(f"获取城市信息失败: 返回数据格式错误，期望非空列表，实际类型：{type(city_data)}")
                return None
            
            # 获取城市ID，处理不同的数据格式
            city_id = None
            if isinstance(city_data[0], dict):
                if "city_id" in city_data[0]:
                    city_id = city_data[0]["city_id"]
                elif "id" in city_data[0]:
                    city_id = city_data[0]["id"]
            elif isinstance(city_data[0], str):
                # 如果返回的是字符串，尝试解析JSON
                try:
                    parsed_data = json.loads(city_data[0])
                    if isinstance(parsed_data, dict):
                        if "city_id" in parsed_data:
                            city_id = parsed_data["city_id"]
                        elif "id" in parsed_data:
                            city_id = parsed_data["id"]
                except json.JSONDecodeError:
                    print(f"解析城市数据失败: 无法解析JSON字符串 {city_data[0]}")
                    return None
            
            if city_id is None:
                print(f"获取城市信息失败: 无法从返回数据中提取城市ID，数据：{city_data}")
                return None
            
            shop_response = await client.get(
                "https://api.wenuu.cn/maimai-report/Data/getData_city.php",
                params={"cityid": city_id},
                timeout=10.0
            )
            shop_response.raise_for_status()
            shop_data = shop_response.json()
            
            # 检查是否返回错误信息
            if isinstance(shop_data, dict) and "error" in shop_data:
                print(f"获取城市机厅信息失败: {shop_data['error']}")
                return None
            
            # 确保shop_data是列表类型
            if not isinstance(shop_data, list):
                print(f"获取城市机厅信息失败: 返回数据格式错误，期望列表类型，实际类型：{type(shop_data)}")
                return None
            
            # 处理每个机厅数据，确保是字典类型
            processed_shop_data = []
            for shop in shop_data:
                if isinstance(shop, dict):
                    processed_shop_data.append(shop)
                elif isinstance(shop, str):
                    try:
                        # 尝试解析JSON字符串
                        parsed_shop = json.loads(shop)
                        if isinstance(parsed_shop, dict):
                            processed_shop_data.append(parsed_shop)
                        else:
                            print(f"警告：机厅数据格式错误，期望字典类型，实际类型：{type(parsed_shop)}")
                    except json.JSONDecodeError:
                        print(f"警告：无法解析机厅数据JSON字符串：{shop}")
                else:
                    print(f"警告：机厅数据格式错误，期望字典类型，实际类型：{type(shop)}")
            
            # 更新缓存
            shop_cache.city_shops[city_name] = processed_shop_data
            shop_cache.last_update[f"city_{city_name}"] = time.time()
            
            # 同时更新单个机厅的缓存
            for shop in processed_shop_data:
                if isinstance(shop, dict) and "id" in shop:
                    shop_id = shop["id"]
                    shop_cache.shop_data[shop_id] = shop
                    shop_cache.last_update[f"shop_{shop_id}"] = time.time()
            
            save_shop_cache(shop_cache)
            return processed_shop_data
    except Exception as e:
        print(f"获取城市机厅信息失败: {str(e)}")
        return None

def get_shop_info(group_id: int, identifier: str) -> Optional[ShopInfo]:
    """通过ID或简称获取机厅信息"""
    subs = group_subscriptions[group_id]
    
    # 先尝试按ID查找
    if identifier.isdigit():
        shop_id = int(identifier)
        if shop_id in subs.shops:
            return subs.shops[shop_id]
    
    # 再尝试按简称查找
    if identifier in global_aliases.alias_to_ids:
        shop_ids = global_aliases.alias_to_ids[identifier]
        for shop_id in shop_ids:
            if shop_id in subs.shops:
                return subs.shops[shop_id]
    
    return None
  
@subscribe.handle()
async def handle_subscribe(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要订阅的机厅ID，多个ID用空格分隔")
    
    try:
        shop_ids = [int(id_str) for id_str in args_str.split()]
    except ValueError:
        await matcher.finish("机厅ID必须是数字，多个ID用空格分隔")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    results = []
    for shop_id in shop_ids:
        if shop_id in subs.shops:
            results.append(f"{shop_id}: 已订阅")
            continue
        
        shop_data = await get_shop_by_id(shop_id)
        if not shop_data:
            results.append(f"{shop_id}: 机厅不存在")
            continue
        
        subs.shops[shop_id] = ShopInfo(id=shop_id)
        results.append(f"{shop_id}: {shop_data['shop_name']} - 订阅成功")
    save_data(group_subscriptions)
    await matcher.finish("\n".join(results))

@unsubscribe.handle()
async def handle_unsubscribe(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要取消订阅的机厅ID，多个ID用空格分隔")
    
    try:
        shop_ids = [int(id_str) for id_str in args_str.split()]
    except ValueError:
        await matcher.finish("机厅ID必须是数字，多个ID用空格分隔")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    results = []
    for shop_id in shop_ids:
        if shop_id not in subs.shops:
            results.append(f"{shop_id}: 未订阅")
            continue
        
        subs.shops.pop(shop_id)
        results.append(f"{shop_id}: 取消订阅成功")
    save_data(group_subscriptions)
    await matcher.finish("\n".join(results))

@add_alias.handle()
async def handle_add_alias(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要添加简称的机厅ID和简称，例如：添加简称 33 f")
    
    parts = args_str.split(maxsplit=1)
    if len(parts) < 2:
        await matcher.finish("请输入机厅ID和简称，例如：添加简称 33 f")
    
    shop_id_str, alias = parts
    if not shop_id_str.isdigit():
        await matcher.finish("机厅ID必须是数字")
    
    group_id = event.group_id
    shop_id = int(shop_id_str)
    subs = group_subscriptions[group_id]
    
    if shop_id not in subs.shops:
        await matcher.finish(f"未订阅ID为{shop_id}的机厅，请先订阅")
    
    # 检查机厅是否已经有这个简称
    if alias in subs.shops[shop_id].aliases:
        await matcher.finish(f"机厅 {shop_id} 已经有简称: {alias}")
    
    # 添加简称到机厅
    subs.shops[shop_id].aliases.add(alias)
    
    # 添加到全局简称映射
    if alias not in global_aliases.alias_to_ids:
        global_aliases.alias_to_ids[alias] = []
    
    if shop_id not in global_aliases.alias_to_ids[alias]:
        global_aliases.alias_to_ids[alias].append(shop_id)
    
    save_data(group_subscriptions)
    save_global_aliases(global_aliases)
    
    # 获取机厅名称
    shop_data = await get_shop_by_id(shop_id)
    shop_name = shop_data['shop_name'] if shop_data else f"机厅{shop_id}"
    
    await matcher.finish(f"已为机厅 {shop_id} ({shop_name}) 添加简称: {alias}")

@remove_alias.handle()
async def handle_remove_alias(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入要删除简称的机厅ID和简称，例如：删除简称 33 f")
    
    parts = args_str.split(maxsplit=1)
    if len(parts) < 2:
        await matcher.finish("请输入机厅ID和简称，例如：删除简称 33 f")
    
    shop_id_str, alias = parts
    if not shop_id_str.isdigit():
        await matcher.finish("机厅ID必须是数字")
    
    group_id = event.group_id
    shop_id = int(shop_id_str)
    subs = group_subscriptions[group_id]
    
    if shop_id not in subs.shops:
        await matcher.finish(f"未订阅ID为{shop_id}的机厅")
    
    if alias not in subs.shops[shop_id].aliases:
        await matcher.finish(f"机厅 {shop_id} 没有简称: {alias}")
    
    # 从机厅中删除简称
    subs.shops[shop_id].aliases.remove(alias)
    
    # 从全局简称映射中删除
    if alias in global_aliases.alias_to_ids and shop_id in global_aliases.alias_to_ids[alias]:
        global_aliases.alias_to_ids[alias].remove(shop_id)
        # 如果该简称没有关联任何机厅，则删除该简称
        if not global_aliases.alias_to_ids[alias]:
            global_aliases.alias_to_ids.pop(alias)
    
    save_data(group_subscriptions)
    save_global_aliases(global_aliases)
    
    # 获取机厅名称
    shop_data = await get_shop_by_id(shop_id)
    shop_name = shop_data['shop_name'] if shop_data else f"机厅{shop_id}"
    
    await matcher.finish(f"已删除机厅 {shop_id} ({shop_name}) 的简称: {alias}")

@list_aliases.handle()
async def handle_list_aliases(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    args_str = args.extract_plain_text().strip()
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    if args_str:
        # 查看指定机厅的简称
        if not args_str.isdigit():
            await matcher.finish("机厅ID必须是数字")
        
        shop_id = int(args_str)
        if shop_id not in subs.shops:
            await matcher.finish(f"未订阅ID为{shop_id}的机厅")
        
        # 获取该机厅的所有全局简称
        shop_aliases = []
        for alias, shop_ids in global_aliases.alias_to_ids.items():
            if shop_id in shop_ids:
                shop_aliases.append(alias)
        
        if not shop_aliases:
            await matcher.finish(f"机厅 {shop_id} 没有设置简称")
        
        shop_data = await get_shop_by_id(shop_id)
        shop_name = shop_data['shop_name'] if shop_data else "未知机厅"
        await matcher.finish(f"机厅 {shop_id} ({shop_name}) 的简称:\n" + "\n".join(shop_aliases))
    else:
        # 查看所有简称
        if not subs.shops:
            await matcher.finish("本群尚未订阅任何机厅")
        
        # 获取本群订阅的机厅ID列表
        subscribed_shop_ids = set(subs.shops.keys())
        
        # 筛选出本群订阅的机厅使用的简称
        messages = []
        for alias, shop_ids in global_aliases.alias_to_ids.items():
            # 找出本群订阅的机厅
            group_shop_ids = [sid for sid in shop_ids if sid in subscribed_shop_ids]
            if group_shop_ids:
                # 获取第一个机厅的信息作为示例
                shop_data = await get_shop_by_id(group_shop_ids[0])
                shop_name = shop_data['shop_name'] if shop_data else "未知机厅"
                
                # 显示简称和关联的机厅ID
                messages.append(f"简称 {alias}: 关联机厅 {', '.join([str(sid) for sid in group_shop_ids])}")
        
        if not messages:
            await matcher.finish("本群订阅的机厅均未设置简称")
        
        await matcher.finish("本群机厅简称列表:\n" + "\n".join(messages))

@jtj.handle()
async def handle_jtj(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    identifier = args.extract_plain_text().strip()
    group_id = event.group_id
    
    if not identifier:
        # 查询订阅的机厅
        subs = group_subscriptions[group_id]
        if not subs.shops:
            #await matcher.finish("本群尚未订阅任何机厅")
            return
        
        messages = []
        for shop_id, shop_info in subs.shops.items():
            shop_data = await get_shop_by_id(shop_id)
            if shop_data:
                # 更新本地记录的最后人数
                shop_info.last_number = int(shop_data.get("shop_number", 0))
                
                predicted = shop_data.get("predicted_number", "无预测数据")
                messages.append(
                    #f"ID：{shop_id}\n"
                    f"{shop_data['shop_name']}({shop_id})\n"
                    #f"简称：{aliases}\n"
                    f"当前：{shop_info.last_number} 人"
                    #f"预测人数：{predicted}\n"
                    #"--------------------"
                )
        
        await matcher.send("\n\n".join(messages))
        return
    
    # 检查是否是简称
    if identifier in global_aliases.alias_to_ids:
        shop_ids = global_aliases.alias_to_ids[identifier]
        # 检查群组是否订阅了这些机厅
        subs = group_subscriptions[group_id]
        subscribed_shop_ids = [shop_id for shop_id in shop_ids if shop_id in subs.shops]
        
        if subscribed_shop_ids:
            messages = []
            for shop_id in subscribed_shop_ids:
                shop_data = await get_shop_by_id(shop_id)
                if shop_data:
                    predicted = shop_data.get("predicted_number", "无预测数据")
                    messages.append(
                        f"{shop_data['shop_name']}({shop_id})\n"
                        f"当前：{shop_data['shop_number']} 人\n"
                        f"来源：{shop_data['shop_source']}"
                    )
            
            if messages:
                await matcher.send("\n\n".join(messages))
                return
              
    # 检查是否是机厅ID
    if identifier.isdigit():
        shop_id = int(identifier)
        shop_data = await get_shop_by_id(shop_id)
        if shop_data:
            messages = [
                f"{shop_data['shop_name']}({shop_id})\n"
                f"当前：{shop_data['shop_number']} 人\n"
                f"来源：{shop_data['shop_source']}"
            ]
            await matcher.send("\n\n".join(messages))
            return
        else:
            await matcher.finish(f"未找到ID为{shop_id}的机厅信息")
            return
    
    # 当作城市名查询
    await matcher.send(f"正在查询{identifier}的机厅信息，请稍候...")
    shop_data = await get_city_shops(identifier)
    if not shop_data:
        await matcher.finish(f"没有查到{identifier}的机厅信息")
    
    messages = [f"{identifier}的机厅信息如下："]
    for shop in shop_data:
        # 确保shop是字典类型
        if isinstance(shop, dict):
            try:
                shop_id = shop.get('id', '未知ID')
                shop_name = shop.get('shop_name', '未知机厅')
                messages.append(f"{shop_id}.{shop_name}")
            except Exception as e:
                print(f"处理机厅数据时出错: {str(e)}, 数据: {shop}")
        else:
            # 如果不是字典类型，记录错误并跳过
            print(f"警告：机厅数据格式错误，期望字典类型，实际类型：{type(shop)}")
    
    await matcher.send("\n".join(messages))
    

@apply_shop.handle()
async def handle_apply_shop(bot:Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()):
    """处理申请机厅请求"""
    args_str = args.extract_plain_text().strip()
    if not args_str:
        await matcher.finish("请输入机厅名称和所在城市，例如：申请机厅 新机厅 杭州")
    
    parts = args_str.split(maxsplit=1)
    if len(parts) < 2:
        await matcher.finish("请输入机厅名称和所在城市，例如：申请机厅 新机厅 杭州")
    
    shop_name, city = parts
    
    # 获取申请者信息
    user_id = event.get_user_id()
    
    # 判断是群聊还是私聊
    if isinstance(event, GroupMessageEvent):
        # 群聊申请
        user_info = await bot.get_group_member_info(group_id=event.group_id, user_id=user_id)
        user_nickname = user_info.get('nickname', '') + "(" + user_id + ")"
        group_id = event.group_id
        
        # 构建申请信息
        apply_info = (
            f"收到新的机厅申请（群聊）：\n"
            f"机厅名称：{shop_name}\n"
            f"所在城市：{city}\n"
            f"申请者：{user_nickname}\n"
            f"申请群组：{group_id}"
        )
    else:
        # 私聊申请
        user_info = await bot.get_stranger_info(user_id=user_id)
        user_nickname = user_info.get('nickname', '') + "(" + user_id + ")"
        
        # 构建申请信息
        apply_info = (
            f"收到新的机厅申请（私聊）：\n"
            f"机厅名称：{shop_name}\n"
            f"所在城市：{city}\n"
            f"申请者：{user_nickname}"
        )
    
    # 转发给超级用户
    await bot.send_private_msg(user_id=SUPER_USER_ID, message=apply_info)
    await matcher.finish("成功提交机厅申请，请等待审核",reply_message=True)

@subscribe_city.handle()
async def handle_subscribe_city(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    """处理订阅城市所有机厅的请求"""
    city_name = args.extract_plain_text().strip()
    if not city_name:
        await matcher.finish("请输入要订阅的城市名称")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    # 获取城市所有机厅
    await matcher.send(f"正在获取{city_name}的机厅信息，请稍候...")
    shop_data = await get_city_shops(city_name)
    if not shop_data:
        await matcher.finish(f"没有查到{city_name}的机厅信息")
    
    # 订阅所有机厅
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
        results.append(f"{shop_id}: {shop_name} - 订阅成功")
    
    save_data(group_subscriptions)
    
    if new_subscriptions == 0:
        if already_subscribed > 0:
            await matcher.finish(f"已订阅{city_name}的所有机厅，共{already_subscribed}个")
        else:
            await matcher.finish(f"未能订阅{city_name}的任何机厅")
    else:
        summary = f"成功订阅{city_name}的{new_subscriptions}个机厅"
        if already_subscribed > 0:
            summary += f"，已有{already_subscribed}个机厅被订阅"
        
        await matcher.finish(f"{summary}\n\n" + "\n".join(results))

@unsubscribe_city.handle()
async def handle_unsubscribe_city(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    """处理取消订阅城市所有机厅的请求"""
    city_name = args.extract_plain_text().strip()
    if not city_name:
        await matcher.finish("请输入要取消订阅的城市名称")
    
    group_id = event.group_id
    subs = group_subscriptions[group_id]
    
    # 获取城市所有机厅
    await matcher.send(f"正在获取{city_name}的机厅信息，请稍候...")
    shop_data = await get_city_shops(city_name)
    if not shop_data:
        await matcher.finish(f"没有查到{city_name}的机厅信息")
    
    # 取消订阅所有机厅
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
        results.append(f"{shop_id}: {shop_name} - 取消订阅成功")
    
    save_data(group_subscriptions)
    
    if unsubscribed == 0:
        if not_subscribed > 0:
            await matcher.finish(f"未订阅{city_name}的任何机厅")
        else:
            await matcher.finish(f"未能取消订阅{city_name}的任何机厅")
    else:
        summary = f"成功取消订阅{city_name}的{unsubscribed}个机厅"
        if not_subscribed > 0:
            summary += f"，有{not_subscribed}个机厅未被订阅"
        
        await matcher.finish(f"{summary}\n\n" + "\n".join(results))

# 定时更新缓存的任务
async def update_cache_task():
    """定时更新缓存数据的任务"""
    while True:
        try:
            print("开始定时更新缓存数据...")
            
            # 更新所有已订阅机厅的缓存
            for group_id, subs in group_subscriptions.items():
                for shop_id in subs.shops:
                    await get_shop_by_id(shop_id)
            
            # 更新所有城市的缓存
            # 这里需要先获取所有城市列表，然后更新每个城市的机厅
            # 由于没有直接获取所有城市的API，这里先不实现
            
            print("缓存数据更新完成")
            
            # 保存更新后的缓存
            save_shop_cache(shop_cache)
            
            # 每10分钟更新一次
            await asyncio.sleep(600)
        except Exception as e:
            print(f"更新缓存数据失败: {str(e)}")
            # 出错后等待5分钟再试
            await asyncio.sleep(300)

# 启动定时任务
driver = get_driver()

@driver.on_startup
async def _():
    """插件启动时启动定时任务"""
    asyncio.create_task(update_cache_task())
