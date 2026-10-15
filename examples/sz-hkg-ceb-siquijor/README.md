# 案例：清湖北站 → 深圳湾口岸 → HKG → CEB → 锡基霍尔（v17）

这是流水线跑通的完整实例（2026-10-13 ~ 10-15，v7→v17 共 11 轮迭代）。
成片 `sz_hkg_ceb_siquijor_trip_v17.mp4`：1920×1080 · 30fps · 1213 帧 / 40.43s。
完整复盘见 `references/case-study-v17.md`。

## 时间轴（40.4s）

| 时间 | 载具 | 路段 |
|---|---|---|
| 0–5.1s | 🚗 car_sz（蓝） | 清湖北站 → 深圳湾口岸（OSRM 27.0km） |
| 5.1–6.3s | 步行虚线 | 口岸深圳侧 → 香港侧（234m 过关） |
| 6.3–11.3s | 🚗 car_hk（黄） | 口岸 → 香港机场（OSRM 36.3km 跨海） |
| 11.3–12.8s | 步行虚线 | HKG 出发大厅 → 跑道口（3949m） |
| 13.3–23.3s | ✈️ | HKG → CEB 真实航路（FL350，~1790km，含 5.8Mm 世界弧线拉远） |
| 23.3–24.8s | 步行虚线 | CEB 停机位 → 出发口（1283m） |
| 24.8–28.9s | 🚗 | CEB → 宿务码头 Pier 1（OSRM 13.8km） |
| 28.9–34.4s | ⛴️ | OceanJet：宿务 → 塔比拉兰 → 锡基霍尔 |
| 34.4–38.4s | 🛵 | 锡基霍尔码头 → U Story 度假村（最后一程） |
| 38.4–40.4s | 🛵 停靠 | 摩托停在度假村，全景拉远 4670km |

## 文件

| 文件 | 角色 |
|---|---|
| `trip_v10.py` | 生成器：产出 3 个新 esp + `flight_data30.json`，内置 bit-exact 接缝断言 |
| `flight_data28.json` | **输入**：上一版（v28）数据 —— 迭代模式 = 新脚本读旧数据复用未变段落 |
| `route_SZ_raw.json` / `route_HK2_raw.json` | **输入**：OSRM 驾车几何 `[[lon,lat],...]` |
| `HKG to CEB Flight.esp` | **输入**：esp 模板（build_esp 以它为底改关键帧） |
| `topdown10v5.esp` / `trip24_seg3_ferry.esp` | **输入**：早前段落的 esp（接缝断言的对照端） |
| `flight_data30.json` | **输出样例**：route 3721 点 / samples 405 / frames 1213 / walks 3 / emoji 朝向 / 全部锚点 |

## 运行

```bash
# 在一个包含上述输入文件的工作目录：
PYTHONPATH=<repo>/compose python3 trip_v10.py
# 输出：trip30_seg0_szhk_v2.esp / trip30_seg1_cebwalk.esp / trip30_seg2_drivev2.esp
#       + flight_data30.json，末尾自动打印 4 处接缝 kf diff（必须全 0）
```

## 复用注意

- 本例是**增量迭代**：飞行段沿用 `topdown10v5.esp`、船/摩托沿用 `trip24_seg3_ferry.esp` 的渲染帧（"改数据不改渲染"，esp md5 对比验证逐字节不变，无需重渲）。全量重做一条新路线时，每个段落都要自己生成 esp + 云渲染。
- `trip_v10.py` 里 v17 的 tail remap（结尾摩托定格）与 walk 顶点生成（`_walk_ckpt` hermite 平台曲线）是最值得抄的两段。
- esp 接缝断言（`_seam_diff` < 1e-12）是硬门槛，新路线生成器应保留同样结构。
