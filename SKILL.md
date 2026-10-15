---
name: trip-video
description: |
  制作"地理行程长视频"（多段交通 + 飞机航线 + Google Earth Studio 云渲染 + 合成出片）的完整流水线。
  当用户要为一条（可能全新的）旅行路线做 Earth Studio 视频时使用：地面导航查询（OSRM）、
  飞机真实航路调研（Tavily）、渡轮/海路、esp 生成、CDP 自动化云渲染、帧合成、QC、编码与 NAS 交付。
  已跑通的样例：清湖北站→深圳湾口岸→HKG→CEB→锡基霍尔（v17）。
---

# Trip Video（Earth Studio 行程长视频）制作流水线

> **本 skill 即一个 git repo**（`kinopico-zhang/trip-video-skill`）。下文 `$T` = repo 根
> （本机：`~/.claude/skills/trip-video` → 软链 `~/workspace/trip-video-skill`）。
> 工作约定：**每个路线一个独立工作目录**（数据 json / esp / 帧都放那边），脚本从 `$T` 调用。
> 深度细节在 `$T/references/`：`case-study-v17.md`（v7→v17 全案复盘，动手前先读）、
> `presentation-rules.md`（呈现规则，用户确认勿倒退）。完整案例：`$T/examples/sz-hkg-ceb-siquijor/`。

## 0. 管线总览

```
路线调研（OSRM 驾车线 / Tavily 航路 / 渡轮线）          ← §1–§2
  ↓  写 per-route 生成脚本（抄 examples/）→ 逐段 .esp + flight_data.json   ← §3
Windows headless Chrome CDP 自动化 Earth Studio 云渲染   ← §4
  ↓  siq_dl.mjs 下载 mp4 → ffmpeg 解码成基础帧
src_frames/（1-indexed f%05d.jpg）
  ↓  compose20.py 合成（路线/载具/步行虚线/标签/图标）
comp_frames/（0-indexed）→ qc + MAD 频闪检查            ← §5
  ↓  ffmpeg 编码（crf 18）
scp nas:/share/Public/earth/ + 双端 md5                 ← §6
```

数据文件 `flight_data.json`（schema 见 examples 里的 `flight_data30.json`）：
`route` 逐顶点 (lat,lon,alt,rt) + walk 标志、`samples` 0.1s 相机采样、`frames` 每帧载具 kind/位置/切向量、
`walks` 步行窗口、`emoji` 各载具精灵朝向角、命名锚点（机场/码头/口岸/起点…）、`fps`。

环境：node≥22（cdp 脚本零依赖）；Pillow 走 `PYTHONPATH`（本机指向 `~/workspace/google-earth/pylibs`，机器无系统 PIL）；ffmpeg 在 `/home/admin/.local/bin/ffmpeg`；**无 numpy**（一切用 PIL）；NAS 用 ssh 别名 `nas`，交付目录 `/share/Public/earth/`。

---

## 1. 地面导航查询（OSRM）

驾车段几何用公共 OSRM demo（Google Maps directions RPC 在 headless 下不可达；OSRM 跟随同样的路网）：

```bash
# 两点驾车线（overview=full 拿全几何）；多点分号串联可强制经由地。机器无 jq，用 python 取坐标
curl -s 'https://router.project-osrm.org/route/v1/driving/114.0354,22.6748;113.9350,22.5101?overview=full&geometries=geojson' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); json.dump(d["routes"][0]["geometry"]["coordinates"], open("route_SZ_raw.json","w"))'
# 结果 [[lon,lat],...]（注意经度在前！），存 route_<段名>_raw.json
```

- **端点钉定**：OSRM 端点吸附到路面、不在精确锚点 → `_load_forced`（examples 的 trip_v10.py 有实现）把首尾钉到精确锚点：距锚点 >25m 插入，否则替换。
- **涉水段校验**：跨海大桥是合法海上高架；用 Natural Earth `ne_50m_land` 点在多边形判断线段是否落水，区分"高架"与"OSRM 绕水犯错"。
- **步行段**（过关/大厅→跑道/停机位→出口）：1–2s，距离地图量测即可，**不查路网**；位移走 ECEF 弦长 hermite 平台曲线（`_walk_ckpt`，两端 0 速、τ=0.3s）。
- **渡轮/海路**：OSRM 无船线 → Tavily 查渡轮公司/航线/码头，路线手工在海上画。

## 2. 飞机航线查询（Tavily 调研 → WPTS）

航路必须调研真实数据建模，**不能拿大圆线糊弄**。用 §7 的 tvly 查清五件事：

1. **出发跑道与初始航向**（样例：HKG 07L/07R，track 073° 向东）
2. **离场 waypoints 序列**（073°→BREAM 右转→ATTOL→SIKOU 避大屿山 934m 峰）
3. **巡航高度与总里程**（FL350=10668m，~1790km）
4. **航路走向**（沿吕宋西侧外海→塔布拉斯海峡→内格罗斯以西→塔尼翁海峡）
5. **到达跑道与进近方向**（CEB 落 04，盛行东北风）

检索关键词：`"<DEP> <ARR> flight route waypoints"`、`"<ICAO> departure chart SID"`；交叉验证 flightradar24 航路页、airport diagrams。产出 = 生成脚本里的 `WPTS` 列表（examples 的 flight10.py 模式：`(lat, lon)` + 跑道头/抬轮点/各 waypoint 注释），航迹线 = 过 waypoints 的 Catmull-Rom 样条。调研结论落脚本 docstring 并记日期。

## 3. 相机设计与 esp 生成（per-route 脚本）

生成器模式（抄 `$T/examples/sz-hkg-ceb-siquijor/trip_v10.py`）：每段一个 `.esp` + 汇总 `flight_data.json`，库在 `$T/compose/`（`flight.py`/`flight_v5.py`：ll2ecef、CAL 表、hermite、`build_esp`）。核心数学（**全部实测验证，勿改**）：

- **ES 插值语义**：云渲染 = 关键帧**数值空间线性插值**；高度在 CAL value（对数）空间插值，写 kf 用 `alt_to_value()`；特大缩放段（≥Mm 拉远）必须在 **v_write 空间**插值。
- **相机基向量**（look-at 自算，与 ES 渲染 ≤1px 对齐）：`f=norm(poi−cam)`，`r=norm(cross(f,norm(cam)))`，`u=cross(r,f)`（`u=cross(f,r)` 会上下镜像）。
- **俯视北朝上**：相机在目标正上方，look-at 目标 = 相机地面点**北移 0.007·H**（≈0.4° 倾斜，heading 恒 0 无抖动）。
- **kf 密度**：0.1s 采样起步；**运动密集时间轴必须逐帧 kf**（0.1s+线性插值会把 H 缩放压成折线、10Hz 表观速度脉冲 1.6×）。
- **平滑运镜 = H 缩放**：平移量取 `du/df = c·s(f)·H(f)`（s=零速端点缓动）→ 屏速与高度无关；巡航段包络法 `v(t)=COEF·H(t)`（里程方程反解 COEF）得恒定屏速 ~700px/s。
- **大跨度缩放在 log 空间**插值 + sinease；多锚点用三次 Hermite + 手设切线（smoothstep 每锚点速度归零会卡顿）。
- **段间 bit-exact 接缝**：后段首帧相机状态逐字取邻段 `camera_state()` 端点写入；生成器内置 `_seam_diff` 断言 < 1e-12（kf 差必须 = 0；实测帧差 1–16 只剩云渲染噪声）。
- **帧数陷阱**：一律 `int(round(T*FPS))`（`int(4.1*30)=122≠123`）。

## 4. Earth Studio 云渲染（CDP 自动化）

前置：Windows Chrome `--headless=new --remote-debugging-port=9222 --user-data-dir=C:\Users\admin\ChromeESAuto`（Chrome 136+ 必须独立 user-data-dir）已登录 ES；WSL2 mirrored 网络直连 `http://localhost:9222`。

```bash
node $T/cdp/nav_es.mjs                      # 恢复/打开 ES + 修窗口 1920×1080（视口每次导入/刷新后重置回 985px，都要重跑！）
node $T/cdp/siq_import.mjs 'C:\Users\admin\ChromeESAuto\seg0.esp'   # 导入 esp（Windows 路径）
node $T/cdp/siq_scrub_batch.mjs 45 45 15 …  # ArrowRight 逐帧步进读属性面板（经度/纬度/海拔）对比设计值
node $T/cdp/render_submit.mjs "Seg0"        # DOM click 打开渲染对话框 + Submit（云渲染 1080p mp4，~2 分钟/段）
node $T/cdp/siq_poll.mjs "Seg0" 15          # 轮询队列至 delivered（提交后 API 几秒才登记，"NONE"≠失败）
node $T/cdp/siq_dl.mjs get "Seg0"           # 队列模态框下载；用完 `siq_dl.mjs close`
```

**CDP 三大坑（脚本已内置对策，原理见 case-study §4）**：
- esp 导入：`DOM.setFileInputFiles` 后**必须手动 dispatch change 事件**，否则 ES 静默失败；导入只进内存不落盘 → 从 live 状态直接 Submit。
- 合成鼠标点击导入后**随机失效** → 渲染按钮/Submit 一律 DOM `el.click()`（render_submit.mjs）。
- React 受控输入偶尔不收注入的作业名 → 用 esp 默认名提交、按默认名轮询下载（**siq_dl.mjs get 必须带 job 名**，否则下错文件）；bigstore 直链 404 别走。
- 属性面板 >350km 高度显示偏低 8–17%（显示 bug，渲染路径准确，勿被误导）。
- 凭据不落盘：登录用 `node $T/cdp/login2.mjs <password>`（argv 传入）。

## 5. 帧装配、合成与呈现规则

```bash
# 解码（mp4 f00001 = t=0，1-indexed）
/home/admin/.local/bin/ffmpeg -i seg0.mp4 -qscale:v 1 seg0_frames/f%05d.jpg
# 按时间轴重命名进 src_frames/（1-indexed 连续）

# 合成（KEEP_WM=1 = 保留 Google logo，唯一交付形态）
cd <工作目录>
FLIGHT_DATA=flight_data.json SRC=src_frames OUT=comp_frames KEEP_WM=1 \
  PYTHONPATH=<Pillow 路径> python3 $T/compose/compose20.py
FLIGHT_DATA=flight_data.json SRC=src_frames OUT=comp_frames \
  PYTHONPATH=<Pillow 路径> python3 $T/compose/compose20.py qc

# MAD 频闪（192×108 灰度相邻帧差）：median≤14 静景 / 20–27 log 变焦梯级 / >40 频闪
PYTHONPATH=<Pillow 路径> python3 $T/qc/mad_check.py comp_frames
```

**呈现规则全文在 `$T/references/presentation-rules.md`（用户确认，勿倒退），要点**：
logo 必留单一版本；步行 = 动态虚线不画人；结尾不追加车辆；图标严格 ∝1/alt（`13500/alt`，0.12 地板）+ 底图长边 150px 同高度等大；载具预等待 + 精确锚点停靠（等待→停靠→当前顺序绘制）。

**compose20.py 逐路线编辑点**（其余全部数据驱动）：
- `AIRPORTS` / `PIERS` 标签列表（文案 / 时间窗 / 淡出）——锚点坐标来自 flight_data.json；
- `FONT_PATH`（CJK 字体，按机器改）；
- 载具精灵 `compose/emoji_*.png`（新载具种类用 `sprite_prep.py` 从 `raw_sprites/` 生成）。

QC 要全绿再编码：停靠/等待锚点投影 0.00px、emoji 全帧在界（±80px）、接缝 esp kf 差 = 0、QC 窗口**按数据实测 rt 段**写（别凭设计时长）。表观速度预算：中心平移 ≤1.2 屏/s、载具 ≤0.8 屏/s。

## 6. 编码与交付

```bash
/home/admin/.local/bin/ffmpeg -framerate 30 -i comp_frames/f%05d.jpg \
  -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -fps_mode passthrough \
  -movflags +faststart <route>_trip_v17.mp4
scp <route>_trip_v17.mp4 nas:/share/Public/earth/
md5sum <route>_trip_v17.mp4 && ssh nas md5sum /share/Public/earth/<route>_trip_v17.mp4   # 双端一致才算交付
```

版本策略：NAS 保留历史通过版本，删除被否/被替代版本；单一 logo 版交付（无 `_logo` 后缀双版本）。

---

## 7. Tavily 检索速查（本机已认证）

`tvly` 在 `/home/admin/.local/bin/tvly`（已 `tvly login`）。JSON 输出适合 LLM 消费：

```bash
tvly search "HKG CEB flight route waypoints FL350" --max-results 8 --include-answer basic
tvly search "Cebu to Siquijor OceanJet ferry schedule pier" --max-results 5 -o ferry.json
tvly extract 'https://www.flightradar24.com/...'           # 全文提取
tvly map 'earth.google.com' --limit 20                     # 站点 URL 发现
tvly research "香港机场 07L 跑道 SID 离场航路"              # 深度调研（多轮，适合航路考证）
```

更全用法见 `~/.claude/skills/tavily-*` 系列 skill。

## 8. 大坑速查

| 坑 | 对策 |
|---|---|
| OSRM 端点不在锚点 | `_load_forced` 钉定（>25m 插入/否则替换） |
| esp 导入静默失败 | 手动 dispatch change 事件（siq_import.mjs 已内置） |
| 合成鼠标点击失效 | DOM `el.click()`（render_submit.mjs） |
| 作业名注入不生效 | 用 esp 默认名提交+轮询下载 |
| 队列刚提交查无此 job | API 延迟数秒，poll 再判 |
| 视口重置 985px | 每次导入/刷新后 `node $T/cdp/nav_es.mjs` |
| 高度显示 >350km 偏低 | 面板显示 bug，以渲染为准 |
| numpy 不存在 | PIL ImageChops/histogram |
| 时间轴抖动/频闪 | 逐帧 kf + log 空间缩放 + H 缩放运镜 + mad_check.py |
| Read 工具看不了渲染帧 | 裁剪→resize→ASCII 显微镜（` .:-=+*#%@`）肉眼查 |
| 账号 botguard 拦截 | 逐字符 dispatchKeyEvent + 鼠标插值（login2.mjs） |
| 凭据 | 一律 argv/环境变量传入，绝不写进 repo |
