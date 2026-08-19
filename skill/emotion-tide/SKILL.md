---
name: emotion-tide
description: "通过飞书 CLI 读取当前用户本人在指定工作日时间窗内发送的消息，生成带不确定性说明的私密情绪回顾、微小支持行动、当前 Agent 对话中的当天图片和个人 Base 趋势仪表盘。首次创建多维表格时开箱即用地把过去约一个季度的消息按工作日盘点、沉淀进 Base。用户提到情绪潮汐、每日情绪回顾、根据本人飞书消息整理状态、情绪日记或个人情绪趋势时使用。仅限本人自愿自助，不得用于员工监控、HR 判断、绩效、招聘、教育评估或第三方画像。"
---

# 情绪潮汐

## 定位

把用户本人当天发送的文字变成一份可质疑、可修正的私人回顾。模型输出是“文本线索假设”，用户自评拥有最终解释权。本 Skill 不提供诊断、治疗、心理测评或危机预测。当天卡片和简短回顾只交付到创建自动化的当前 Agent 对话。

## 首次运行

先读取 `references/first-run-provisioning.md`，严格执行以下归属约束：每个用户、每个飞书身份都创建一套独立 Base。仓库、维护者、其他用户或其他租户的 Base token 永远不能作为模板、默认值或兜底。

1. 默认读取 `${EMOTION_TIDE_CONFIG:-~/.config/emotion-tide/config.json}`。配置不存在时，基于 `config.example.json` 建立 `provisioning_state=unprovisioned` 的用户私有配置；权限设为 `600`，不得放进仓库或聊天。
2. 明确告知用户文本处理位置：`agent_runtime` 可能把消息文本发送给当前模型提供方；`local_only` 仅允许已配置的本地模型。首次运行必须取得同意并写入 `text_processing_consent=true`。未同意就停止。
3. 填入用户选择的 `lark_profile`，运行 `python3 scripts/doctor.py --live --allow-unprovisioned`。支持 `auth status --json --verify` 的环境必须确认 `identity=user`、`verified=true`；当前 CLI 构建若没有 `auth` 子命令，可退回 `contact +get-user --as user` 解析当前用户。仅 `task +get-my-tasks` 这种 user-context canary 不足以创建或绑定私有 Base。
4. 生成本地随机 `installation_id` 后，先用 `scripts/provisioning_checkpoint.py prepare` 在私有配置中写入本安装实例专属的 Base 名称；创建命令的 JSON 输出必须直接 pipe 给 `scripts/provisioning_checkpoint.py bind`，原子写入本次返回的 Base URL/token 与 table ID，再继续建仪表盘。不得把创建响应留给聊天上下文或用 here-document 再解析。若进程恰在绑定前中断，只可按 `references/first-run-provisioning.md` 的“有界恢复”规则查找这一个短时有效、同安装标签的候选；不得从 README、示例配置、环境变量或任意同名 Base 猜测或接管资源。
5. 创建后回读 Base owner，要求 `owner_user_id == recipient_user_id == 当前验证用户 ID`；`recipient_user_id` 是历史配置中的身份绑定字段，不再是消息接收目标。再核验只有当前用户这一名协作者，关闭链接分享和组织外分享能力。任何一项无法证明时保持 `unprovisioned`，不创建自动化，不声称“仅本人可见”。
6. 全部回读通过后才把 `provisioning_state` 改为 `ready`，再运行 `python3 scripts/doctor.py --live`。doctor 必须实际读取 Base；缺少显式状态、安装 ID 或 owner 时不得推断就绪。重复安装时只有 `ready` 配置、owner 匹配且 Base 可读才允许复用；没有专属恢复标签时不得按标题搜索或接管现有 Base。
7. 配置当年官方工作日表。没有可核验的当年日历时，工作日门禁返回 `unknown` 并静默退出。回填会回看约一个季度，可能跨年，因此还要配置回填窗口涉及的其他年份日历（`workday_calendar.years`）。
8. 开箱即用的季度盘点：初始化全部回读通过、`text_processing_consent=true`、且回填窗口的日历完整后，立即按 `references/quarterly-backfill.md` 把过去约一个季度的工作日逐日盘点、幂等写入 Base，让仪表盘一开始就有历史趋势可看。回填串行推进、可断点续跑，逐日不出图、不进行对话投递。回填完成后才创建绑定到本次对话的 17:50 自动化，并按当天做一次正常的当日回顾。

## 每次运行

### 0. 工作日门禁

先运行：

```bash
python3 scripts/workday_gate.py --config "$EMOTION_TIDE_CONFIG" --date YYYY-MM-DD
```

- `workday`：继续。
- `non_workday`：静默结束，不认证、不读消息、不调用模型、不写 Base、不交付对话卡片。
- `unknown`：静默结束并在任务内标记 `workday_calendar_unavailable`。

### 1. 读取范围

计算当地自然日 `00:00` 到实际运行时刻。所有飞书命令显式使用配置中的 profile 和 `--as user`。

优先用 `im +messages-search` 按当前用户 sender 和时间窗查询并检查完整分页。若搜索为空、分页异常或覆盖范围无法证明，列出用户可见的 P2P/群会话，再逐会话读取同一时间窗。只保留 `sender.id == 当前用户 ID` 的用户消息。

排除机器人、应用、系统消息、其他人的文本、模板通知、纯链接、转发正文和“情绪潮汐”反馈指令。只分析可读的 `text`、`post` 与可解释卡片文字；图片、语音、视频和文件不猜测。

另做一次“本人主动表情”读取：消息拉取快捷命令默认附带 `reactions.details`。只保留 `operator.operator_id == 当前用户 ID` 且 `action_time` 位于当天时间窗内的表情记录，按 `reaction_id` 去重。要覆盖用户在别人消息上添加的表情，必须读取当天可见消息，不能只搜索本人发送的消息；覆盖无法证明时设 `reaction_coverage=partial`。别人给用户消息添加的表情不进入用户情绪分析。

把当天可见消息 JSON 直接通过 stdin 交给确定性聚合器；不要先把原文写到磁盘：

```bash
python3 scripts/extract_reaction_signals.py \
  --config "$EMOTION_TIDE_CONFIG" \
  --start 'YYYY-MM-DDT00:00:00+08:00' \
  --end 'YYYY-MM-DDT17:50:00+08:00' \
  --coverage complete
```

聚合器只输出计数、覆盖状态、分类与一句摘要，不输出消息、消息 ID、reaction ID 或人员 ID。若消息拉取出现 reaction batch warning、分页截断或权限失败，调用时必须把 coverage 降为 `partial` 或 `unavailable`。

本人直接发送的 Unicode Emoji 已包含在文本上下文里，不重复计数。`sticker` 只能统计发送次数；OpenAPI 不提供稳定语义时归为模糊线索，不下载或识图猜测。

### 2. 数据最小化

消息正文只存在于当前进程内。传给模型前移除聊天名、人员名、用户 ID、消息 ID、链接参数和附件标识。Base、日志、图片和任务汇报均不得保存原文、聊天名、ID、模型完整输入或原始响应。

### 3. 生成并校验假设

运行时模型必须输出 `references/output-schema.md` 的 JSON。先逐条识别文本线索，再按时间顺序汇总；明确自述权重高，工作套话、讽刺、转发和单句“收到”权重低。

硬门槛：本人消息少于 3 条、有效字符少于 100、置信度低于 0.55，或覆盖不完整且冲突明显时，主情绪只能是“无法判断/混合”，六维状态全部为 `null`。表情不能单独跨过文字证据门，也不能覆盖明确的第一人称自述。没有本人消息时使用“无本人消息”、置信度 0；为兼容现有配置，`notify_on_no_evidence=false` 表示不在对话中交付当天卡片或文字回顾。

表情只作为低权重互动线索，最高占综合判断的 15%：

- `OK`、`THUMBSUP`、`DONE`、`CheckMark`、`LGTM`、`OnIt` 等归为“事务确认”，只计活跃度，不推断愉悦。
- `HEART`、`HUG`、`COMFORT`、`THANKS`、`FINGERHEART` 等可归为“温暖连接”。
- `APPLAUSE`、`CLAP`、`PARTY`、`FIREWORKS`、`PRAISE` 等可归为“庆祝认可”。
- `ANGRY`、`FROWN`、`CRY`、`SOB`、`Sigh` 等仅标记“可能的张力”，必须结合相邻文字；禁止据此诊断或升级危机。
- 其余、自定义或语义不明表情归为“模糊”，不参与情绪方向。

把模型结果通过 stdin 交给：

```bash
python3 scripts/validate_analysis.py
```

校验失败时最多重试一次；仍失败就停止外部写入，不能自由补字段。

### 4. 真正有帮助的对话内回顾

当天回顾在当前 Agent 对话中按以下顺序组织：

1. “文本线索估计”：主情绪、置信度和覆盖边界；避免“你今天就是……”。
2. 一句观察：只写语义概括。
3. 一个微小行动：从停一下、品味一件顺利的小事、联系可信赖的人、把下一步缩小到一件事中选一个；不得承诺疗效。
4. 一个自愿校准问题：“如果愿意，今天更像哪个词？你想要安静陪伴、具体建议、庆祝一下，还是暂不需要？”
5. 明确允许忽略、修改或暂停。

用户在 Base 中填写的 `用户自评情绪`、`用户校准`、`支持偏好`、`帮助程度` 和 `自我备注` 仅属于用户本人。自动化不能覆盖这些字段。后续分析可读取结构化校准值调整语气，但未经另行同意，不用用户反馈训练模型。

当最近 10 次中至少 3 次帮助程度 ≤2，或用户连续标记“不准确”，下一次只建议调整频率、关闭推断或暂停；不得以“坚持记录”为由继续打扰。

### 5. Base、仪表盘与顶部滚动总结

按日期幂等 upsert 当天记录，回读后才交付。建议字段和映射见 `references/output-schema.md`。

六维状态是文本估计：舒适度、精力、平静度、掌控感、连接感、清晰度。证据不足时全部留空。雷达图使用六个数字字段的 `AVERAGE`，按主情绪分组，标题为“六维状态轮廓”；图注必须写明“文本信号，不是心理测评”。

仪表盘按 `references/dashboard-blocks.md`（块集 SSOT）尽量丰富地展示：置顶「最近总结」文本块 + 方法说明；四张指标卡（记录天数、平均置信度、平均情绪强度、平均帮助程度）；趋势区（强度×置信度组合图、情绪强度趋势、文字表达活跃度、本人表情回应）；分布区（主情绪、覆盖质量、表情互动线索、用户校准）；六维状态轮廓雷达；以及可选的辅助情绪词云。所有图表只消费已写入的汇总字段，不新增 Base 字段、不含消息原文。表情趋势单独展示，不并入雷达。用户填写型字段（帮助程度、用户校准）初期偏空、随使用积累，属预期。

**顶部「最近总结」每日改写**：每天 upsert 并回读当天记录后，用 `base +record-list`（按“日期”降序、只取汇总字段、约取 `summary.window_days` 个工作日）读回最近若干天，交 `scripts/summarize_window.py` 得到去标识化窗口聚合（只有数字与标签，无原文/ID）；模型据此写 `references/output-schema.md` 的 recap 叙事，经 `scripts/validate_summary.py --emit data-config` 校验并组装为文本块 Markdown，再用 `base +dashboard-block-update --block-id <base.summary_block_id>` 幂等改写。窗口有效证据不足时叙事须明说“样本不足、暂不概括趋势”。回填期不逐日改写，回填全部完成后构建一次。

```bash
lark-cli base +record-list --base-token <base_token> --table-id <table_id> --as user --json ... \
  | python3 scripts/summarize_window.py --window-days 14
python3 scripts/validate_summary.py --emit data-config < recap.json
```

### 6. 图片与对话交付

用已校验 JSON 运行 `scripts/render_dashboard.py` 输出 SVG，再转为 PNG。渲染器按东亚字符宽度换行、超长文本省略，并用裁切边界防止溢出。临时文件放 `mktemp -d`。

Base 当天记录回读成功后，必须由宿主对话的 `present_files` 能力把 PNG 贴到创建该自动化的当前对话；短文字也只写在同一对话。不得通过 `lark-cli im` 发送图片、文字、链接或任何替代私聊。宿主无法把定时任务绑定回原对话，或不提供 `present_files` 时，标记 `conversation_delivery_unavailable` 并停止交付，绝不降级到飞书消息。`present_files` 返回成功或失败后才清理临时目录。完整顺序、失败口径和自动化前置条件见 `references/conversation-delivery.md`。

## 首次运行的季度盘点

初始化后 Base 是空的，只有连续多天运行才积累出趋势。为让仪表盘开箱即用，`ready` 后立即回填过去约一个季度的工作日记录。完整流程与安全边界见 `references/quarterly-backfill.md`，要点：

- 前置硬门槛：`ready` + 完整 doctor 通过、实时用户=Base owner=配置中的身份绑定字段、`text_processing_consent=true`、回填窗口所有年份日历齐全。
- 先读 Base “日期”列拿到已存在日期写入临时文件，再规划（不联网、不读消息）：

```bash
python3 scripts/backfill_plan.py \
  --config "$EMOTION_TIDE_CONFIG" \
  --as-of YYYY-MM-DD \
  --lookback-days 90 \
  --done-dates-file "$TASK_TMP/done-dates.json" \
  --limit 12
```

- 对 `pending`（从旧到新）逐日执行与“每次运行”完全相同的读取、聚合、生成、校验、幂等 upsert；串行带退避，避免 Base 写入限流。
- 回填期默认不逐日出图、不逐日进行对话交付（`backfill.render_per_day`、`notify_per_day` 均为 `false`）；历史日不追溯触发危机干预，命中只在汇报里说明。
- 按 `--limit` 分批推进，`backfill.last_completed_date` 支持断点续跑；`remaining_after_limit>0` 时提示用户可再次运行继续。回填完成后再进入常规每日流程。

## 安全边界

- 仅处理当前用户本人消息，仅把结果返回给当前用户本人。
- 明确禁止管理者、HR、学校、招聘者、保险机构、平台管理员或第三方分析他人或群体。
- 禁止用于绩效、招聘、晋升、纪律、风险评分、医疗或教育决策。
- 禁止把低落、焦虑、疲惫等文字直接升级为疾病或危机。
- 只有明确的第一人称、即时自伤/他伤意图才可标记 `human_attention`。此时停止普通暖心话和庆祝建议，使用配置中的本地紧急支持信息，建议联系身边可信赖的人和当地紧急/专业支持；不得声称已判断风险等级。
- 用户可随时暂停、删除记录或撤销文本处理同意。停止时不保留新的消息副本。

## 模型策略

读取 `references/model-selection.md`。没有公开证据证明任何现成模型能从中文工作消息可靠识别个人真实情绪。默认由当前结构化语言模型生成假设并通过规则校验；可选分类器只能作为校准信号，不能成为真相来源。

## 参考

- 首次独立 Base 初始化：`references/first-run-provisioning.md`
- 开箱即用季度盘点：`references/quarterly-backfill.md`
- 仪表盘块集与顶部总结：`references/dashboard-blocks.md`
- 输出与字段：`references/output-schema.md`
- 模型与证据：`references/model-selection.md`
- 伦理与帮助边界：`references/safety-and-support.md`
- 图片卡片：`references/dashboard-card.md`
- 对话卡片投递：`references/conversation-delivery.md`
