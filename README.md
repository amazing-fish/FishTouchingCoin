# FishTouchingCoin

摸鱼币：常驻桌面角落的摸鱼收益计时器（仅 Windows）。工作时段内你不碰键鼠、或锁屏离开（带薪时长内），就按时薪累计“摸鱼收入”。

## 低调设计
- 悬浮窗平时只是一个暗灰色的小数字，没有 ¥、没有状态文字，旁人看不出是什么。
- 鼠标悬停满 3 秒才展开：状态、周末倍率、4 位小数；移开立即收起。
- `F9` 一键隐藏/显示；隐藏期间照常计费。
- 托盘提示与详情窗口标题不出现“摸鱼”字样。

## 使用
- 左键拖动，双击打开统计，右键菜单：暂停计费、详情、配置、开机自启、隐藏、重置今日、退出。
- 托盘图标常驻：单击显示/隐藏，右键菜单同上。
- 计费规则：09:00 前、午休、下班后不计费；工作时段空闲 ≥ 阈值计费；锁屏在带薪时长内计费，超时停止；周末按倍率。

## 运行与开发
```bash
pip install -r requirements-dev.txt
python fish.py
python -m pytest -q
```

## 结构
```
fishcoin/
  domain/   纯逻辑（settings / schedule / meter / ledger），可单测
  infra/    存储（原子写）与 Windows 系统能力（WTS 锁屏、互斥锁、注册表自启、DWM）
  ui/       悬浮窗、菜单、统计、配置、托盘、主题
  app.py    组装根：采样 → 计费 → 渲染 → 落盘
```

## 数据
`%APPDATA%\FishTouchingCoin\`：`settings.json`（配置）、`ledger.json`（每日收入，保留 365 天）、`app.log`。

v0.7.0 起不再读取旧版 `data_schema_v1.json` / `settings_schema_v1.json`，旧文件原样保留。

## 版本
`v主.次.修`，技术路径与修改日志见 `ANCHOR.md`。
