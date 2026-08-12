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
| 覆盖状态 | select | 覆盖统计 |
| 情绪摘要、观察线索、暖心话语、微小行动 | text | 模型输出，不含原文 |
| 文本舒适度、文本精力、文本平静度 | number | 六维文本假设，可空 |
| 文本掌控感、文本连接感、文本清晰度 | number | 六维文本假设，可空 |
| 分析模型、运行时间、人工关注 | text/datetime/select | 审计字段 |
| 用户自评情绪、用户校准、支持偏好 | select | 仅用户填写，自动化不得覆盖 |
| 帮助程度 | rating 1–5 | 仅用户填写，自动化不得覆盖 |
| 自我备注 | text | 仅用户自愿填写，自动化不得复制消息原文 |

任何部署都不能添加消息原文、聊天名称、人员 ID、消息 ID、完整 prompt、模型原始响应或公开分享链接字段。
