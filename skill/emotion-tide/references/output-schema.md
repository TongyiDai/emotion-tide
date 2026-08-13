# 输出与 Base 字段

## 模型 JSON

```json
{
  "date": "2026-08-12",
  "primary_emotion": "无本人消息",
  "secondary_emotions": [],
  "intensity": 0.0,
  "confidence": 0.0,
  "coverage": "no_user_messages",
  "message_count": 0,
  "effective_text_count": 0,
  "effective_char_count": 0,
  "reaction_count": 0,
  "effective_reaction_count": 0,
  "reaction_coverage": "complete",
  "reaction_signal": "none",
  "reaction_summary": "当天未识别到本人主动添加的表情回应。",
  "observed": [],
  "inference": "文本证据不足，暂不判断。",
  "uncertainty": "本人消息不足。",
  "summary": "今天没有足够的本人消息可供回顾。",
  "warm_words": "今天可以不做解释。",
  "reflection_prompt": "如果愿意，今天更像哪个词？",
  "micro_action": "把注意力放回呼吸一分钟。",
  "dimensions": {
    "comfort": null,
    "energy": null,
    "calm": null,
    "agency": null,
    "connection": null,
    "clarity": null
  },
  "attention_flag": "none",
  "attention_reason": null
}
```

允许值：

- `primary_emotion`：平稳、愉悦、充实、焦虑、疲惫、低落、烦躁、受挫、感激、惊喜、混合、无法判断、无本人消息。
- `coverage`：`complete`、`partial`、`no_user_messages`、`unreadable`。
- `attention_flag`：`none`、`human_attention`。
- `attention_reason`：`null` 或 `explicit_immediate_risk`。
- `reaction_coverage`：`complete`、`partial`、`unavailable`。
- `reaction_signal`：`none`、`acknowledgement`、`warmth`、`celebration`、`tension`、`mixed`、`ambiguous`。
- 所有六维值、强度、置信度：0–1；弱证据时六维必须全部为 `null`。
- 输出必须只含上述字段；额外字段会被拒绝。日期必须使用 `YYYY-MM-DD`。
- `message_count=0` 必须与 `coverage=no_user_messages`、`primary_emotion=无本人消息`、零强度/置信度同时出现。

## Base 字段

| 字段 | 类型 | 来源 |
|---|---|---|
| 日期 | text | 机器写入，日期唯一键 |
| 主情绪、辅助情绪 | select | 文本假设 |
| 情绪强度、置信度 | number | 文本假设 |
| 本人消息数、有效文本数、有效字符数 | number | 覆盖统计 |
| 本人表情回应数、有效表情线索数 | number | 本人主动添加的表情统计 |
| 表情覆盖状态、表情互动线索 | select/text | 低权重互动线索 |
| 覆盖状态 | select | 覆盖统计 |
| 情绪摘要、观察线索、暖心话语、微小行动 | text | 模型输出，不含原文 |
| 文本舒适度、文本精力、文本平静度 | number | 六维文本假设，可空 |
| 文本掌控感、文本连接感、文本清晰度 | number | 六维文本假设，可空 |
| 分析模型、运行时间、人工关注 | text/datetime/select | 审计字段 |
| 用户自评情绪、用户校准、支持偏好 | select | 仅用户填写，自动化不得覆盖 |
| 帮助程度 | rating 1–5 | 仅用户填写，自动化不得覆盖 |
| 自我备注 | text | 仅用户自愿填写，自动化不得复制消息原文 |

任何部署都不能添加消息原文、聊天名称、人员 ID、消息 ID、完整 prompt、模型原始响应或公开分享链接字段。

“本人表情回应数”只统计当前用户主动添加的 reaction 与无法解析语义的本人 sticker；别人添加给用户消息的 reaction 不计入。表情不能单独跨过文字证据门，不能直接改变六维雷达。

## 顶部「最近总结」recap 叙事 JSON

顶部文本块由模型据 `scripts/summarize_window.py` 的去标识化窗口聚合生成，经 `scripts/validate_summary.py` 校验。聚合只含数字与标签（有证据天数、均强度/均置信度、主情绪分布与主导情绪、六维均值及最高/最低维、覆盖质量、表情信号分布、上/下半段强度趋势），不含原文、聊天名或 ID。模型输出固定 schema：

```json
{
  "window_label": "近 14 个工作日",
  "headline": "整体平稳，后半段强度略升。",
  "narrative": [
    "有效记录 9 天，主导情绪偏向平稳与充实。",
    "六维里连接感最高、精力最低，可留意休息。",
    "覆盖多为完整，判断可信度中等。"
  ],
  "gentle_note": "这是文本线索，不是结论；今天想调整或暂停都可以。",
  "as_of": "2026-08-13"
}
```

- `window_label`、`headline`、`gentle_note`：非空字符串，分别 ≤40、≤40、≤60 字。
- `narrative`：1–4 条，每条 ≤60 字。
- `as_of`：`YYYY-MM-DD`。
- 校验器强制附「文本信号，非心理测评」免责，禁止诊断词，拒绝多余字段。窗口有效证据不足时叙事必须说明“样本不足、暂不概括趋势”。

新增仪表盘图表（强度×置信度组合图、覆盖质量分布、表情互动线索分布、用户校准分布、平均情绪强度/帮助程度指标卡等）全部复用上表既有字段聚合，不新增任何 Base 字段；模板见 `references/dashboard-blocks.md`。
