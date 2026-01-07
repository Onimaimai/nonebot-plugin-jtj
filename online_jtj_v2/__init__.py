from nonebot import get_driver
from nonebot.plugin import PluginMetadata
import asyncio

# 导入 handlers 以注册命令
from .handlers import *

# 导入定时任务
from .services.tasks import update_cache_task

__plugin_meta__ = PluginMetadata(
    name="机厅",
    description="查询和更新机厅人数",
    usage="""
    jtj <城市/简称/id> - 查询指定机厅
    jtj - 查询本群订阅的机厅
    订阅机厅 <id1> [id2]... - 订阅多个机厅(空格分隔)
    退订机厅 <id1> [id2]... - 退订多个机厅(空格分隔)
    订阅城市 <城市> - 订阅指定城市的所有机厅
    退订城市 <城市> - 退订指定城市的所有机厅
    添加简称 <id> <简称> - 为机厅添加简称
    删除简称 <id> <简称> - 删除机厅的简称
    查看简称 [id] - 查看所有简称或指定机厅的简称
    机厅静默 <开启/关闭> - 设置本群机厅消息静默模式
    <简称><数字> - 直接更新人数(如:万达10)
    <简称>+<数字> - 增加人数(如:万达+2)
    <简称>-<数字> - 减少人数(如:万达-1)
    附近机厅 - 查询附近机厅
    新建机厅 - 申请添加机厅
    审核机厅 - 超级用户审核新添加机厅
    清空审核机厅 - 超级用户清空待审核机厅列表
    """
)

# 启动定时任务
driver = get_driver()

@driver.on_startup
async def _():
    """插件启动时启动定时任务"""
    asyncio.create_task(update_cache_task())
