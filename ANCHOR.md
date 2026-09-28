# Anchor 文档

## 版本规范
- 版本号采用 `v主.次.修`，并在修改日志中标注 `feature/refactor/bugfix` 类型；版本常量在 `fishcoin/__init__.py`。

## 第一性原理
- 今日收入 = ∫ 费率(t) × 是否摸鱼(t) dt。计费规则是纯逻辑（`fishcoin/domain`），展示与系统集成围绕它组装。
- 这是摸鱼工具：默认形态必须低调，信息只在用户主动交互（悬停、打开窗口）时展开。

## 技术路径
- 分层：`domain`（无 tkinter/ctypes，时间注入，pytest 覆盖）→ `infra`（存储、Windows API）→ `ui` → `app.py` 组装。
- 计费：`Meter.tick(Sample)` 每 100ms 一次；单 tick 最多计 1 秒，防休眠/断点跳变；计费与窗口是否可见无关。
- 锁屏：`WTSQuerySessionInformation(WTSSessionInfoEx).SessionFlags` 判定，0.5s 缓存；查询失败按“未知”回退为空闲计费。锁屏计时跟随真实锁屏会话，跨午休/跨天不重置。
- 账本：`ledger.json` 按日期一条记录（money、last_after_work），今天的收入即当天记录，无“日结”快照。
- 配置：`Settings` 不可变 dataclass，缺字段取默认，校验失败视为首次启动并备份损坏文件。上班时间固定 09:00（内部字段，UI 不暴露）。
- 开机自启：注册表 `HKCU\...\Run` 是唯一事实来源，不在 settings 中冗余保存。
- 单实例：命名互斥锁 `Local\FishTouchingCoin.SingleInstance`，进程退出由系统回收。
- 悬浮窗：overrideredirect + DWM 圆角（Win11），平时暗灰数字、0.62 透明度，悬停展开；按“全 0”模板测宽避免抖动；右下角锚定。
- 悬浮窗被系统最小化（Win+D/Win+M）时转为隐藏，只留托盘，不产生桌面左下角的最小化标题条。
- 统计/配置窗口创建后先 withdraw，布局完成并居中后再显示（`ui/windowing.present`），避免先在左上角闪现。
- 右键菜单：自绘 Toplevel，失焦即关，替代 `tk.Menu` 以规避其 grab/焦点问题。
- 托盘：pystray 常驻独立线程，菜单事件经 `queue` 交回 Tk 主线程；提示文案保持中性。
- 主循环 try/finally 保证持续调度；Tk 回调异常与运行日志写入 `app.log`。
- 打包：PyInstaller `--add-data app.ico;.`，资源经 `sys._MEIPASS` 解析。

## 修改日志
- v0.1.x feature/refactor/bugfix: 托盘化与依赖补齐、18:00 日结与历史记录、历史记录合并进数据文件。
- v0.2.x feature/bugfix/refactor: 数据迁移到本地用户目录；托盘详情与趋势弹窗；计费/锁屏与窗口焦点修复；版本常量与历史写盘策略整理。
- v0.3.x refactor/bugfix: 拆分配置、存储、系统调用与 UI 逻辑模块；增强非 Windows 降级与配置时间边界校验。
- v0.4.x feature/refactor/bugfix: 下班后最后使用时间、单实例锁、详情弹窗精简、右键菜单样式与收起修复、周末高亮。
- v0.5.x feature/refactor: 右键菜单开机自启开关；整理修改日志。
- v0.6.x feature/bugfix: 配置页开机自启选项；启动不强制改写注册表。
- v0.7.0 refactor/bugfix/feature: 第一性原理重构为 domain/infra/ui 分层并补齐单测；修复锁屏检测（旧方案永不返回锁屏，带薪上限从未生效）；计费与窗口可见性解耦；新数据格式且不兼容旧文件；仅支持 Windows；悬浮窗低调化、自绘菜单、统计与配置页重设计；修复主循环异常断链、托盘跨线程调用 Tk、打包缺托盘图标、日结快照过期。
- v0.7.1 bugfix: 系统最小化悬浮窗时改为隐藏到托盘，不再残留最小化标题条；统计/配置窗口居中后再显示，修复先在左上角闪现。

## 理想规划
- 进军 Web3，成为摸鱼界的代币；当前实现的只是最适合落地的一个小功能。
- 阶段一（现实落地）：完善桌面端体验与数据可信度，打磨计费与统计，后续将持续优化人机交互和视觉。
- 阶段二（资产化雏形）：引入可验证的摸鱼积分与身份体系，支持可视化排行与成就。
- 阶段三（代币化演进）：探索链上发行与治理机制，建立摸鱼生态的激励与协作模式。
