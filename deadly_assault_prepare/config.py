from __future__ import annotations

from one_dragon.base.operation.application.application_config import ApplicationConfig

from . import const


class DeadlyAssaultPrepareConfig(ApplicationConfig):
    """危局强袭战-预处理配置。"""

    def __init__(self, instance_idx: int, group_id: str) -> None:
        super().__init__(
            app_id=const.APP_ID,
            instance_idx=instance_idx,
            group_id=group_id,
        )

    @property
    def cycle_anchor_dt(self) -> str:
        """危局强袭战双周周五刷新基准日 (yyyyMMdd，默认 20261120 周五 04:00)"""
        return self.get('cycle_anchor_dt', '20261120')

    @cycle_anchor_dt.setter
    def cycle_anchor_dt(self, value: str) -> None:
        self.update('cycle_anchor_dt', value)
