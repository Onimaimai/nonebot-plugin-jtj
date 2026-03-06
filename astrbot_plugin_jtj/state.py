from .services.data_manager import DataManager

# 初始化所有数据
# 这些变量在内存中保存应用程序的状态，并在更改时由 DataManager 保存到磁盘
group_subscriptions = DataManager.load_subscriptions()
shop_cache = DataManager.load_shop_cache()
global_aliases = DataManager.load_global_aliases()
review_cache = DataManager.load_review_cache()
silent_mode_config = DataManager.load_silent_mode()
rate_limit_data = DataManager.load_rate_limit_data()
report_stats = DataManager.load_report_stats()