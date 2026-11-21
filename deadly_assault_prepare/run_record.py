from __future__ import annotations

import datetime
import os
import time
from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.config import yaml_operator
from one_dragon.base.operation.application_run_record import AppRunRecord
from one_dragon.utils import os_utils
from one_dragon.utils.log_utils import log

from . import const

if TYPE_CHECKING:
    from .config import DeadlyAssaultPrepareConfig


class DeadlyAssaultPrepareRunRecord(AppRunRecord):
    """危局强袭战-预处理运行记录与双周周期判断。

    规则：
    - 与危局强袭战相同，按 14 天周五凌晨 04:00 双周周期刷新（基准 2026-11-20）。
    - 与完整模式/战斗模式共享本周期最终完成状态：若 `deadly_assault` 或 `deadly_assault_battle`
      在本周期已完成全部挑战，则预处理自动跳过（`is_done == True`）。
    - 若本周期仅完成了预处理，记录仅标记预处理自身已完成，不会阻挡后续 `deadly_assault_battle`
      或 `deadly_assault` 的战斗执行。
    """

    DEFAULT_ANCHOR_DT: ClassVar[str] = '20261120'
    CYCLE_DAYS: ClassVar[int] = 14
    TOTAL_SLOTS: ClassVar[int] = 3

    def __init__(
        self,
        config: DeadlyAssaultPrepareConfig | None = None,
        instance_idx: int | None = None,
        game_refresh_hour_offset: int = 0,
    ) -> None:
        self.config: DeadlyAssaultPrepareConfig | None = config
        super().__init__(
            app_id=const.APP_ID,
            instance_idx=instance_idx,
            game_refresh_hour_offset=game_refresh_hour_offset,
        )

    @staticmethod
    def _is_valid_dt(dt_str: object) -> bool:
        if not isinstance(dt_str, str) or len(dt_str) != 8 or not dt_str.isdigit():
            return False
        try:
            datetime.datetime.strptime(dt_str, '%Y%m%d')
            return True
        except ValueError:
            return False

    def get_anchor_dt(self) -> str:
        if self.config is not None:
            anchor = self.config.cycle_anchor_dt
            if self._is_valid_dt(anchor):
                return anchor
        return self.DEFAULT_ANCHOR_DT

    def get_period_start_dt(self, dt: str | None = None) -> str:
        target_dt = dt if dt is not None else self.get_current_dt()
        anchor_dt = self.get_anchor_dt()
        delta_days = os_utils.dt_day_diff(target_dt, anchor_dt)
        cycle_index = delta_days // self.CYCLE_DAYS
        return os_utils.add_dt_offset(anchor_dt, cycle_index * self.CYCLE_DAYS)

    def get_next_refresh_dt(self, dt: str | None = None) -> str:
        return os_utils.add_dt_offset(self.get_period_start_dt(dt), self.CYCLE_DAYS)

    @property
    def recorded_period_start_dt(self) -> str:
        stored = self.get('period_start_dt', '')
        if self._is_valid_dt(stored):
            return stored
        if self._is_valid_dt(self.dt):
            return self.get_period_start_dt(self.dt)
        return ''

    def _should_reset_by_dt(self) -> bool:
        current_dt = self.get_current_dt()
        recorded_period = self.recorded_period_start_dt
        if not recorded_period:
            return True
        return recorded_period != self.get_period_start_dt(current_dt)

    def _is_sibling_finished_for_period(self, sibling_app_id: str, target_period: str) -> bool:
        """检查完整模式在当前 14 天周期是否已完成完整战斗与领奖。"""
        if self.file_path is None:
            return False
        sibling_path = os.path.join(os.path.dirname(self.file_path), f'{sibling_app_id}.yml')
        if not os.path.exists(sibling_path):
            return False
        try:
            data = yaml_operator.read_cache_or_load(sibling_path)
        except Exception:
            return False
        if not isinstance(data, dict):
            return False

        sib_period = data.get('period_start_dt', '')
        if not self._is_valid_dt(sib_period):
            sib_dt = data.get('dt', '')
            if not self._is_valid_dt(sib_dt):
                return False
            sib_period = self.get_period_start_dt(sib_dt)

        if sib_period != target_period:
            return False
        if bool(data.get('prepare_only_pending', False)):
            return False
        return bool(data.get('full_completed', False)) or data.get('run_status') == AppRunRecord.STATUS_SUCCESS

    @property
    def is_finished_by_period(self) -> bool:
        """当前周期已完成预处理，或者完整模式已通关本周期时返回 True。"""
        current_period = self.get_period_start_dt(self.get_current_dt())
        if not self._should_reset_by_dt() and self.run_status == AppRunRecord.STATUS_SUCCESS:
            return True
        return self._is_sibling_finished_for_period('deadly_assault', current_period)

    @property
    def is_done(self) -> bool:
        return self.is_finished_by_period

    @property
    def run_status_under_now(self) -> int:
        if self.is_finished_by_period:
            return AppRunRecord.STATUS_SUCCESS
        if self._should_reset_by_dt():
            return AppRunRecord.STATUS_WAIT
        if self.dt != self.get_current_dt():
            return AppRunRecord.STATUS_WAIT
        return self.run_status

    def update_status(self, new_status: int, only_status: bool = False) -> None:
        self.run_status = new_status
        self.update('run_status', self.run_status, False)
        if not only_status:
            self.dt = self.get_current_dt()
            self.run_time = self.app_record_now_time_str()
            self.run_time_float = time.time()
            self.update('dt', self.dt, False)
            self.update('run_time', self.run_time, False)
            self.update('run_time_float', self.run_time_float, False)
            self.update('period_start_dt', self.get_period_start_dt(self.dt), False)
        self.save()

    def reset_record(self) -> None:
        AppRunRecord.reset_record(self)
        self.update('period_start_dt', self.get_period_start_dt(self.get_current_dt()), False)
        self.save()

    def check_and_update_status(self) -> None:
        current_dt = self.get_current_dt()
        if self._should_reset_by_dt():
            log.info(
                '检测到危局强袭战-预处理进入新周期（上一周期=%s，当前周期=%s，下期刷新=%s），重置记录',
                self.recorded_period_start_dt or '无',
                self.get_period_start_dt(current_dt),
                self.get_next_refresh_dt(current_dt),
            )
            self.reset_record()
        elif not self.is_finished_by_period and self.dt != current_dt:
            AppRunRecord.reset_record(self)
