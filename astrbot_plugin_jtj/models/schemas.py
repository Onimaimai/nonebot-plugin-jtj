from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional

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

@dataclass
class ReviewCache:
    pending_shops: List[dict] = field(default_factory=list)  # 待审核机厅列表
    last_update: float = 0  # 最后更新时间
    
    def to_dict(self):
        return {
            "pending_shops": self.pending_shops,
            "last_update": self.last_update
        }
    
    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        
        return cls(
            pending_shops=data.get("pending_shops", []),
            last_update=data.get("last_update", 0)
        )
    
@dataclass
class SilentModeConfig:
    silent_groups: Set[int] = field(default_factory=set)  # 启用静默模式的群组ID集合
    
    def to_dict(self):
        return {
            "silent_groups": list(self.silent_groups)
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        if not data:
            return cls()
        return cls(
            silent_groups=set(data.get("silent_groups", []))
        )
