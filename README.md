# trip-video-skill

"地理行程长视频"制作 skill：多段交通（驾车/步行/飞机/渡轮/摩托）+ Google Earth Studio 云渲染 + 逐帧合成出片的完整流水线，抽象自跑通的 [清湖北站→HKG→CEB→锡基霍尔 v17](examples/sz-hkg-ceb-siquijor/) 案例。换一条路线也能照做。

## 安装

```bash
git clone git@github.com:kinopico-zhang/trip-video-skill.git
# 方式一：直接 clone 进 Claude Code 的 skill 目录
git clone git@github.com:kinopico-zhang/trip-video-skill.git ~/.claude/skills/trip-video
# 方式二：clone 到任意位置，软链过去
ln -s <clone 路径> ~/.claude/skills/trip-video
```

repo 根即 skill（`SKILL.md` 在根目录）；Claude Code 会自动发现并按需加载。

## 布局

```
SKILL.md                     主工作流（入口，保持精简）
cdp/                         Earth Studio 云渲染 CDP 自动化（.mjs，node>=22，零依赖）
  nav_es.mjs                   打开/恢复 ES 标签页 + 修窗口 1920x1080
  siq_import.mjs               导入 .esp（含 change 事件坑的对策）
  siq_scrub*.mjs               逐帧步进读属性面板，验证导入
  render_submit.mjs            DOM click 打开渲染对话框 + Submit
  siq_poll.mjs / siq_dl.mjs    轮询队列 / 下载成片
  login2.mjs                   账号登录（密码走 argv，不落盘）
  cdp.mjs / ctrlkey.mjs / …    CDP 客户端与调试工具
compose/                     合成器 + 数学库 + 精灵
  compose20.py                 逐帧合成（路线/载具/步行虚线/标签/图标）+ qc
  flight.py / flight_v5.py     相机/esp 数学库（ll2ecef、CAL 表、hermite、build_esp）
  sprite_prep.py               从 raw 底图生成归一化精灵（长边 150px、去白边）
  emoji_*.png                  归一化精灵；raw_sprites/ 为 Noto 源图
qc/mad_check.py              相邻帧 MAD 频闪检查（纯 PIL，无 numpy）
examples/sz-hkg-ceb-siquijor/ v17 完整案例（生成器 + 输入输出数据 + README）
references/                  深度参考
  case-study-v17.md            v17 全案复盘（数学推导、11 轮迭代、踩坑细节）
  presentation-rules.md        呈现规则（用户确认，勿倒退）
```

## 依赖

| 依赖 | 说明 |
|---|---|
| node ≥ 22 | cdp/ 脚本用全局 WebSocket/fetch |
| Pillow | 合成器唯一 Python 依赖；`PYTHONPATH` 指向任意含 Pillow 的路径（或装进所用解释器的环境） |
| ffmpeg | 解码渲染帧 / 最终编码（crf 18） |
| Windows Chrome + CDP | `--headless=new --remote-debugging-port=9222` + 独立 user-data-dir，登录 Earth Studio |
| CJK 字体 | compose20.py `FONT_PATH` 指向 msyh.ttc，按机器改 |
| tvly（Tavily CLI） | 航路/渡轮调研（可选但强烈推荐） |

凭据政策：本 repo 不含任何账号/密码；ES 登录密码经 `login2.mjs` argv 传入，用后即弃。

## 用法

对 Claude Code 说"用 trip-video skill 做一条 XX→YY 的行程视频"即可；
或直接读 [SKILL.md](SKILL.md) 按流程执行：调研（OSRM/Tavily）→ esp 生成 → CDP 云渲染 → 合成 → QC → 编码交付。
