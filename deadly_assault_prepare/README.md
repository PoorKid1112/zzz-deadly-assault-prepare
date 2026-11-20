# 危局强袭战-预处理 (Deadly Assault Prepare)

《绝区零》一条龙（ZZZOD）「危局强袭战」拆分前置预处理插件，专为消除智能推荐配队约 5 分钟的干等时间而设计。

> 🤝 需搭配末尾战斗插件使用：[危局强袭战-战斗 (`deadly_assault_battle`)](https://github.com/PoorKid1112/zzz-deadly-assault-battle)  
> 📦 若无需拆分等待，也可直接使用单插件完整版：[危局强袭战 (`deadly_assault`)](https://github.com/PoorKid1112/zzz-deadly-assault)

---

## 设计思路与执行流程

在「一条龙」中默认以高优先级（`PRIORITY = 60`）排在日常开头运行：

1. **入场预检** (Step 1 - Step 6)：
   - 自动导航进入「快捷手册 - 作战 -> 危局强袭战（试炼）」，传送进入危局主界面。
   - 扫描下方 3 个首领槽位：若均无 `EMPTY` 且已有成绩，判定本周期已打完，直接跳过配队并返回大世界。
2. **触发配队算队（不等待）** (Step 7 - Step 9)：
   - 打开「配队指引」，自动关闭可能出现的「规则说明」弹窗，切换至「智能推荐」。
   - 点击「生成更多」触发后台配队验算后**立即结束等待**，不阻塞一条龙后续日常（清体力、每周日常、零号空洞等任务运行时游戏后台同步计算推荐配队）。
3. **退出主界面** (Step 12, Step 29)：
   - 返回危局主界面并退回大世界，让后续一条龙日常顺畅衔接，最后由一条龙末尾的「危局强袭战-战斗」直接应用结果并开打。

---

## 双周运行判断与状态共享

- **14 天双周周五 04:00 交替机制**：遵循危局与式舆每周五 04:00 交替刷新的周期规则，式舆刷新周保持完成状态并自动跳过，直到下一期危局刷新再重置。
- **跨插件共享逻辑**：
  - 本插件仅标记「预处理已完成」，**绝不会阻挡**同一天后续「危局强袭战-战斗」或完整版「危局强袭战」执行；
  - 若本周期内「危局强袭战-战斗」或完整版「危局强袭战」已通关并领奖，本插件也会自动在本周期内跳过，避免重复进图。

---

## 插件配置项

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :---: | :---: | :--- |
| `cycle_anchor_dt` | `str` | `"20261120"` | 双周周五刷新基准日（`yyyyMMdd`，默认对应周五 04:00 刷新锚点） |

---

## 文件结构

```text
deadly_assault_prepare/
├── __init__.py
├── const.py                  # APP_ID="deadly_assault_prepare", PRIORITY=60
├── factory.py                # DeadlyAssaultPrepareFactory
├── config.py                 # DeadlyAssaultPrepareConfig
├── run_record.py             # 双周周期判断与共享状态读取
├── screens.py                # 画面识别定义注入
├── app.py                    # DeadlyAssaultPrepareApp
├── plugin.json               # 插件市场元数据清单
├── README.md                 # 中文说明文档
├── screen_info/
│   ├── deadly_assault_prepare_guide.yml
│   ├── deadly_assault_prepare_main.yml
│   └── deadly_assault_prepare_modes.yml
└── assets/
    └── cover.webp
```

---

## 安装与使用

1. 同时安装本插件与「危局强袭战-战斗」后，将本目录放置于 `plugins/deadly_assault_prepare/`。
2. 在一条龙默认日常列表中开启「危局强袭战-预处理」（排在日常最前面）与「危局强袭战-战斗」（排在日常末尾）即可；若已启用这两项，建议关闭完整版「危局强袭战」避免重复。
