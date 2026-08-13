# 仪表盘块集（SSOT）

本文件是「情绪潮汐」仪表盘的组件清单与 `data_config` 模板来源。所有 `data_config` 使用**字段名**（非字段 ID），源表固定为「每日情绪」。所有图表只消费本 skill 已写入的去标识化汇总字段，不新增 Base 字段、不含消息原文。`data_config` 的通用规则以 lark-base 的 `references/dashboard-block-data-config.md` 为准；本文件只固化本 skill 的块集。

创建前用 `+field-list` 确认字段真实存在与类型；按顺序创建（不要并行创建同一仪表盘的多个块），全部创建后调用 `base +dashboard-arrange` 让服务端智能排布。每个块创建返回的 `block_id` 需要时记录；只有「最近总结」文本块的 `block_id` 需要持久化到配置的 `base.summary_block_id`，供每日改写。

## 顺序与块集（约 15 个）

### 1. 文本

**最近总结（置顶，每日改写）** — `--type text`
文本内容由 `scripts/validate_summary.py --emit data-config` 生成；创建时先放占位，随后每日用 `+dashboard-block-update --block-id <summary_block_id>` 覆盖。

```json
{ "text": "# 最近总结\n1. 首次运行后将由每日流程填充。\n\n### 文本信号，非心理测评。可忽略、修改或暂停。" }
```

**方法说明** — `--type text`

```json
{ "text": "# 方法说明\n- 仅分析本人当天消息，非工作日跳过。\n- 六维与情绪均为文本信号，非心理测评。\n- 用户自评与校准字段仅本人填写，自动化不覆盖。" }
```

### 2. 指标卡 `--type statistics`

| 名称 | data_config |
|---|---|
| 记录天数 | `{"table_name":"每日情绪","count_all":true}` |
| 平均置信度 | `{"table_name":"每日情绪","series":[{"field_name":"置信度","rollup":"AVERAGE"}]}` |
| 平均情绪强度 | `{"table_name":"每日情绪","series":[{"field_name":"情绪强度","rollup":"AVERAGE"}]}` |
| 平均帮助程度 | `{"table_name":"每日情绪","series":[{"field_name":"帮助程度","rollup":"AVERAGE"}]}` |

「平均帮助程度」依赖用户填写的评分，初期偏空、随使用积累，属预期。

### 3. 趋势

**强度×置信度组合图** — `--type combo`

```json
{
  "table_name": "每日情绪",
  "series": [
    { "field_name": "情绪强度", "rollup": "AVERAGE" },
    { "field_name": "置信度", "rollup": "AVERAGE" }
  ],
  "group_by": [{ "field_name": "日期", "mode": "integrated", "sort": {"type":"group","order":"asc"} }]
}
```

**情绪强度趋势** — `--type line`（保留，续接历史）

```json
{ "table_name": "每日情绪", "series": [{ "field_name": "情绪强度", "rollup": "AVERAGE" }],
  "group_by": [{ "field_name": "日期", "mode": "integrated", "sort": {"type":"group","order":"asc"} }] }
```

**文字表达活跃度趋势** — `--type line`

```json
{ "table_name": "每日情绪", "series": [{ "field_name": "有效字符数", "rollup": "SUM" }],
  "group_by": [{ "field_name": "日期", "mode": "integrated", "sort": {"type":"group","order":"asc"} }] }
```

**本人表情回应趋势** — `--type area`

```json
{ "table_name": "每日情绪", "series": [{ "field_name": "本人表情回应数", "rollup": "SUM" }],
  "group_by": [{ "field_name": "日期", "mode": "integrated", "sort": {"type":"group","order":"asc"} }] }
```

### 4. 分布

**主情绪分布** — `--type pie`

```json
{ "table_name": "每日情绪", "count_all": true,
  "group_by": [{ "field_name": "主情绪", "mode": "integrated" }] }
```

**覆盖质量分布** — `--type ring`

```json
{ "table_name": "每日情绪", "count_all": true,
  "group_by": [{ "field_name": "覆盖状态", "mode": "integrated" }] }
```

**表情互动线索分布** — `--type pie`

```json
{ "table_name": "每日情绪", "count_all": true,
  "group_by": [{ "field_name": "表情互动线索", "mode": "integrated" }] }
```

**用户校准分布** — `--type bar`

```json
{ "table_name": "每日情绪", "count_all": true,
  "group_by": [{ "field_name": "用户校准", "mode": "integrated" }] }
```

「用户校准」依赖用户填写，初期偏空、随使用积累，属预期。

### 5. 雷达

**六维状态轮廓** — `--type radar`（保留，图注写明「文本信号，不是心理测评」）

```json
{
  "table_name": "每日情绪",
  "series": [
    { "field_name": "文本舒适度", "rollup": "AVERAGE" },
    { "field_name": "文本精力", "rollup": "AVERAGE" },
    { "field_name": "文本平静度", "rollup": "AVERAGE" },
    { "field_name": "文本掌控感", "rollup": "AVERAGE" },
    { "field_name": "文本连接感", "rollup": "AVERAGE" },
    { "field_name": "文本清晰度", "rollup": "AVERAGE" }
  ],
  "group_by": [{ "field_name": "主情绪", "mode": "integrated" }]
}
```

### 6. 可选：辅助情绪词云 — `--type wordCloud`

仅当「辅助情绪」是可分词统计的字段时启用；若为单选或结构不合适，跳过以免生成空图/畸形图。

```json
{ "table_name": "每日情绪", "count_all": true,
  "group_by": [{ "field_name": "辅助情绪", "mode": "integrated" }] }
```

## 每日改写「最近总结」

每日 upsert 当天记录并回读后：

```bash
# 1. 读回最近若干天的汇总字段（按日期 desc，只取汇总字段）
lark-cli base +record-list --base-token <base_token> --table-id <table_id> --as user --json ... \
  | python3 scripts/summarize_window.py --window-days 14

# 2. 模型据聚合写叙事 JSON（见 output-schema.md 的 recap schema），再校验并组装
python3 scripts/validate_summary.py --emit data-config < recap.json

# 3. 幂等改写置顶文本块
lark-cli base +dashboard-block-update --base-token <base_token> \
  --dashboard-id <dashboard_id> --block-id <summary_block_id> \
  --as user --data-config "$(python3 scripts/validate_summary.py --emit data-config < recap.json)"
```

回填期不逐日改写「最近总结」；回填全部完成后构建一次即可。窗口内有效证据不足（`evidence_days` 过少）时，叙事应明说「样本不足、暂不概括趋势」，不要硬凑判断。
