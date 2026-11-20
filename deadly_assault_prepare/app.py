from __future__ import annotations

import os
import re
import time
from typing import ClassVar

import cv2
from cv2.typing import MatLike
import numpy as np

from one_dragon.base.geometry.point import Point
from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_notify import NotifyTiming, node_notify
from one_dragon.base.operation.operation_round_result import OperationRoundResult
from one_dragon.utils.log_utils import log
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld

from . import const
from .config import DeadlyAssaultPrepareConfig
from .run_record import DeadlyAssaultPrepareRunRecord
from .screens import ensure_screens


class DeadlyAssaultPrepareApp(ZApplication):
    """危局强袭战-预处理应用 (Step 1-9 [不等待], Step 12, Step 29)。

    专为「一条龙」前置加速设计：
    1. 在一条龙早期阶段进入危局强袭战，打开「配队指引」->「智能推荐」并点击「生成更多」（不等待验算结果）。
    2. 立即返回危局主界面并退回大世界，让后续一条龙其他日常与后台算队并行，节省约 5 分钟等待时间。
    3. 若进入主界面时发现 3 个首领均已有挑战成绩（本周期已完成），则自动跳过配队直接返回大世界。
    """

    STATUS_NEED_TEAM_GUIDE: ClassVar[str] = '需要触发配队生成'
    STATUS_ALL_BOSSES_DONE: ClassVar[str] = '全部首领已完成'
    SLOT_NAMES: ClassVar[list[str]] = ['槽位-左', '槽位-中', '槽位-右']

    def __init__(
        self,
        ctx: ZContext,
        config: DeadlyAssaultPrepareConfig | None = None,
        run_record: DeadlyAssaultPrepareRunRecord | None = None,
    ) -> None:
        super().__init__(
            ctx=ctx,
            app_id=const.APP_ID,
            op_name=const.APP_NAME,
            run_record=run_record,
        )
        self.config: DeadlyAssaultPrepareConfig = config or DeadlyAssaultPrepareConfig(
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self.run_record: DeadlyAssaultPrepareRunRecord | None

        ensure_screens(self.ctx.screen_loader)

    def save_screenshot(self, prefix: str | None = None) -> str:
        """保存调试截图至 plugin_data/deadly_assault_prepare，不污染主仓库。"""
        if self.last_screenshot is None:
            return ''
        if prefix is None:
            prefix = self.__class__.__name__

        data_dir = self.ctx.get_plugin_data_dir(const.APP_ID)
        os.makedirs(data_dir, exist_ok=True)
        file_name = f"{prefix}_{round(time.time() * 1000)}"
        file_path = os.path.join(data_dir, f"{file_name}.png")

        bgr_image = cv2.cvtColor(self.last_screenshot, cv2.COLOR_RGB2BGR)
        cv2.imwrite(file_path, bgr_image)
        log.info('预处理运行截图已保存至: %s', file_path)
        return file_path

    def is_in_deadly_assault_main(self, screen: MatLike | None) -> bool:
        """判断是否处于危局强袭战主界面。"""
        if screen is None:
            return False
        result = self.round_by_find_area(screen, '危局预处理-主界面', '选定敌方')
        if result.is_success:
            return True
        results = self.ctx.ocr.match_words(
            screen,
            ['选定敌方', '配队指引', '重置全部关卡', '荣誉酬赏'],
            threshold=0.6,
        )
        return len(results) >= 2

    def has_ocr_text(self, screen: MatLike | None, candidates: list[str]) -> bool:
        """全屏 OCR 模糊子串匹配（免疫标点符号/空格干扰）。"""
        if screen is None:
            return False
        for r in self.ctx.ocr.ocr(screen):
            text = r.data.strip()
            if any(cand in text for cand in candidates):
                return True
        return False

    def click_red_feature_in_rect(
        self,
        screen: MatLike | None,
        rect: Rect,
        min_pts: int = 30,
        wait_sec: float = 1.8,
        label: str = '红色按钮',
    ) -> bool:
        """在目标矩形内识别红色按键中心并点击。"""
        if screen is None:
            return False
        h, w = screen.shape[:2]
        screen_1080 = cv2.resize(screen, (1920, 1080)) if (w, h) != (1920, 1080) else screen
        crop = screen_1080[rect.y1:rect.y2, rect.x1:rect.x2]
        r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
        red_pts = np.argwhere((r > 150) & (g < 70) & (b < 70))
        if len(red_pts) < min_pts:
            return False
        min_y, min_x = red_pts.min(axis=0)
        max_y, max_x = red_pts.max(axis=0)
        target = Point(rect.x1 + (min_x + max_x) // 2, rect.y1 + (min_y + max_y) // 2)
        log.info('特征检测到%s位置: (%d, %d)', label, target.x, target.y)
        self.ctx.controller.click(target)
        time.sleep(wait_sec)
        return True

    def scan_slot_states(self, screen: MatLike | None) -> tuple[list[bool], list[bool]]:
        """检查主界面 3 个首领槽位是否均已有成绩（无 EMPTY）。"""
        empty_states: list[bool] = []
        scored_states: list[bool] = []
        if screen is None:
            return [False, False, False], [False, False, False]

        h, w = screen.shape[:2]
        screen_1080 = cv2.resize(screen, (1920, 1080)) if (w, h) != (1920, 1080) else screen

        for name in self.SLOT_NAMES:
            area = self.ctx.screen_loader.get_area('危局预处理-主界面', name)
            crop = screen_1080[area.rect.y1:area.rect.y2, area.rect.x1:area.rect.x2]
            ocr_res = self.ctx.ocr.ocr(crop)

            has_empty = any('EMPTY' in r.data.upper() or 'EMPT' in r.data.upper() for r in ocr_res)
            has_score = any(
                r.rect.x1 >= 45 and re.fullmatch(r'[\d,]{3,}', r.data.strip())
                for r in ocr_res
            )
            empty_states.append(has_empty)
            scored_states.append(not has_empty and has_score)

        return empty_states, scored_states

    # ---------------- 阶段 1: 入场导航 (Step 1 - Step 5) ----------------

    @operation_node(name='开始', is_start_node=True)
    def start_node(self) -> OperationRoundResult:
        """检查初始位置：若已在主界面/快捷手册则直接衔接，否则先返回大世界。"""
        if self.is_in_deadly_assault_main(self.last_screenshot):
            log.info('当前已在危局强袭战主界面')
            return self.round_success('已在危局强袭战主界面')

        res = self.round_by_find_area(self.last_screenshot, '快捷手册', 'TAB列表')
        if res.is_success:
            log.info('当前已在快捷手册')
            return self.round_success('已在快捷手册')

        log.info('返回大世界以开始危局强袭战-预处理')
        op = BackToNormalWorld(self.ctx, ensure_normal_world=True)
        return self.round_by_op_result(op.execute(), status='已返回大世界')

    @node_from(from_name='开始', status='已返回大世界')
    @node_from(from_name='开始', status='已在快捷手册')
    @operation_node(name='进入快捷手册-作战')
    def goto_compendium(self) -> OperationRoundResult:
        """导航到快捷手册-作战 (Step 1-2)。"""
        return self.round_by_goto_screen(screen_name='快捷手册-作战', success_wait=2.0, retry_wait=1.5)

    @node_from(from_name='进入快捷手册-作战')
    @operation_node(name='选择危局强袭战', node_max_retry_times=5)
    def choose_deadly_assault_tab(self) -> OperationRoundResult:
        """点击左侧危局强袭战条目 (Step 3)。"""
        area = self.ctx.screen_loader.get_area('危局预处理-模式选择', '列表-危局强袭战')
        return self.round_by_ocr_and_click(
            self.last_screenshot,
            target_cn='危局强袭战',
            area=area,
            crop_first=False,
            success_wait=2.0,
            retry_wait=1.5,
        )

    @node_from(from_name='选择危局强袭战')
    @operation_node(name='点击试炼前往', node_max_retry_times=5)
    def enter_trial(self) -> OperationRoundResult:
        """点击试炼卡片的前往按钮 (Step 4)。"""
        area = self.ctx.screen_loader.get_area('危局预处理-模式选择', '试炼-前往')
        return self.round_by_ocr_and_click(
            self.last_screenshot,
            target_cn='前往',
            area=area,
            crop_first=False,
            success_wait=2.0,
            retry_wait=1.5,
        )

    @node_from(from_name='点击试炼前往')
    @operation_node(name='确认传送', node_max_retry_times=5)
    def confirm_tp(self) -> OperationRoundResult:
        """点击传送确认弹窗 (Step 5)。"""
        area = self.ctx.screen_loader.get_area('危局预处理-模式选择', '传送-确认')
        return self.round_by_ocr_and_click(
            self.last_screenshot,
            target_cn='确认',
            area=area,
            crop_first=False,
            success_wait=2.5,
            retry_wait=1.5,
        )

    @node_from(from_name='确认传送')
    @node_from(from_name='开始', status='已在危局强袭战主界面')
    @operation_node(name='等待主界面加载')
    def wait_main_screen(self) -> OperationRoundResult:
        """等待危局主界面加载完毕，若本周期 3 个首领均已有成绩则跳过预处理直接结束 (Step 6)。"""
        if self.is_in_deadly_assault_main(self.last_screenshot):
            time.sleep(0.5)
            self.last_screenshot = self.screenshot()
            empty_states, scored_states = self.scan_slot_states(self.last_screenshot)
            if not any(empty_states) and sum(scored_states) >= 2:
                time.sleep(0.5)
                self.last_screenshot = self.screenshot()
                empty_states2, scored_states2 = self.scan_slot_states(self.last_screenshot)
                if not any(empty_states2) and sum(scored_states2) >= 2:
                    log.info('主界面预检：3 个首领槽位均无 EMPTY 且已有成绩，本周期挑战已完成，跳过预处理')
                    return self.round_success(self.STATUS_ALL_BOSSES_DONE)
            return self.round_success(self.STATUS_NEED_TEAM_GUIDE)

        return self.round_wait('等待危局强袭战主界面加载', wait=1.5)

    # ---------------- 阶段 2: 触发智能配队生成（不等待） (Step 6-9, 12) ----------------

    @node_from(from_name='等待主界面加载', status=STATUS_NEED_TEAM_GUIDE)
    @operation_node(name='打开配队指引', node_max_retry_times=5)
    def open_team_guide(self) -> OperationRoundResult:
        """点击主界面配队指引按钮 (Step 6)。"""
        area = self.ctx.screen_loader.get_area('危局预处理-主界面', '配队指引')
        return self.round_by_ocr_and_click(
            self.last_screenshot,
            target_cn='配队指引',
            area=area,
            crop_first=False,
            success_wait=2.0,
            retry_wait=1.5,
        )

    @node_from(from_name='打开配队指引')
    @operation_node(name='检查规则说明弹窗')
    def check_rule_dialog(self) -> OperationRoundResult:
        """检查并关闭可能出现的规则说明弹窗 (Step 7)。"""
        for _ in range(3):
            if self.has_ocr_text(self.last_screenshot, ['规则说明', '规则']):
                break
            if self.has_ocr_text(self.last_screenshot, ['智能推荐', '绳网精选', '生成更多']):
                break
            time.sleep(0.5)
            self.last_screenshot = self.screenshot()

        if self.has_ocr_text(self.last_screenshot, ['规则说明', '规则']):
            log.info('检测到规则说明弹窗，点击关闭')
            click_res = self.round_by_find_and_click_area(
                self.last_screenshot,
                '危局预处理-配队指引',
                '规则说明-关闭',
                success_wait=1.8,
            )
            if click_res.is_success:
                return self.round_success()

            close_area = self.ctx.screen_loader.get_area('危局预处理-配队指引', '规则说明-关闭')
            if close_area is not None and self.click_red_feature_in_rect(
                self.last_screenshot,
                close_area.rect,
                min_pts=30,
                wait_sec=1.8,
                label='规则说明关闭叉号',
            ):
                return self.round_success()

            return self.round_retry('检测到规则说明弹窗但未定位到关闭按钮', wait=1.5)

        log.info('未出现规则说明弹窗，直接进入下一步')
        return self.round_success()

    @node_from(from_name='检查规则说明弹窗')
    @operation_node(name='点击智能推荐', node_max_retry_times=5)
    def click_ai_recommend(self) -> OperationRoundResult:
        """点击智能推荐选项卡 (Step 8)。"""
        if self.has_ocr_text(self.last_screenshot, ['规则说明', '规则']):
            close_area = self.ctx.screen_loader.get_area('危局预处理-配队指引', '规则说明-关闭')
            if close_area is not None:
                self.click_red_feature_in_rect(
                    self.last_screenshot,
                    close_area.rect,
                    min_pts=30,
                    wait_sec=1.5,
                    label='规则说明关闭叉号',
                )

        area = self.ctx.screen_loader.get_area('危局预处理-配队指引', '智能推荐')
        return self.round_by_ocr_and_click(
            self.last_screenshot,
            target_cn='智能推荐',
            area=area,
            crop_first=False,
            success_wait=1.8,
            retry_wait=1.5,
        )

    @node_from(from_name='点击智能推荐')
    @operation_node(name='点击生成更多', node_max_retry_times=5)
    def click_generate_more(self) -> OperationRoundResult:
        """触发生成更多推荐配队后不等待验算，直接进入返回流程 (Step 9)。"""
        area = self.ctx.screen_loader.get_area('危局预处理-配队指引', '生成更多')
        res = self.round_by_ocr_and_click(
            self.last_screenshot,
            target_cn='生成更多',
            area=area,
            crop_first=False,
            success_wait=2.0,
            retry_wait=1.5,
        )
        if res.is_success:
            log.info('已点击生成更多触发后台配队验算（预处理不等待生成结果，直接返回）')
        return res

    @node_from(from_name='点击生成更多')
    @operation_node(name='返回危局主界面', node_max_retry_times=5)
    def back_from_team_guide(self) -> OperationRoundResult:
        """点击配队指引左上角返回按钮回到危局主界面 (Step 12)。"""
        if self.is_in_deadly_assault_main(self.last_screenshot):
            log.info('已回到危局强袭战主界面')
            return self.round_success()

        res = self.round_by_find_and_click_area(
            self.last_screenshot,
            '画面-通用',
            '返回',
            success_wait=2.0,
            retry_wait=1.5,
        )
        if res.is_success:
            return self.round_success()

        if self.click_red_feature_in_rect(
            self.last_screenshot,
            Rect(60, 15, 160, 85),
            min_pts=50,
            wait_sec=2.0,
            label='左上角红色返回按键',
        ):
            return self.round_success()

        return self.round_retry('未检测到配队指引左上角返回按钮', wait=1.5)

    @node_from(from_name='返回危局主界面')
    @operation_node(name='等待回到危局主界面')
    def wait_main_before_exit(self) -> OperationRoundResult:
        """确认已回到危局主界面后再退出至大世界 (Step 12 -> Step 29)。"""
        if self.is_in_deadly_assault_main(self.last_screenshot):
            return self.round_success()
        return self.round_wait('等待回到危局主界面', wait=1.5)

    # ---------------- 阶段 3: 返回大世界完成 (Step 29) ----------------

    @node_from(from_name='等待回到危局主界面')
    @node_from(from_name='等待主界面加载', status=STATUS_ALL_BOSSES_DONE)
    @node_notify(when=NotifyTiming.CURRENT_DONE, detail=True)
    @operation_node(name='返回大世界并结束')
    def back_to_world_finish(self) -> OperationRoundResult:
        """点击左上角返回并返回大世界，结束预处理 (Step 29)。"""
        res = self.round_by_find_and_click_area(
            self.last_screenshot,
            '画面-通用',
            '返回',
            success_wait=2.0,
        )
        if not res.is_success:
            self.click_red_feature_in_rect(
                self.last_screenshot,
                Rect(60, 15, 160, 85),
                min_pts=50,
                wait_sec=2.0,
                label='主界面左上角红色返回按键',
            )

        op = BackToNormalWorld(self.ctx, ensure_normal_world=True)
        op.execute()

        if self.run_record is not None:
            log.info(
                '危局强袭战-预处理完成，可在一条龙后续节点运行「危局强袭战-战斗」（本周期下次刷新日: %s 04:00）',
                self.run_record.get_next_refresh_dt(),
            )
        else:
            log.info('危局强袭战-预处理执行完成')
        return self.round_success('危局强袭战-预处理完成')
