# 首次运行：每位用户独立创建 Base

## 不变量

- 一个 `installation_id` 只绑定一个已验证飞书用户和一套 Base。
- Base owner、配置中的历史身份绑定字段、消息读取主体必须是同一个当前用户；当天回顾只在当前 Agent 对话中交付。
- 公开仓库与示例配置只含 `null`，不提供任何可连接的 Base、用户或租户标识。
- 禁止复制维护者 Base、复用其他用户 token、按普通同名标题猜测 Base，或切换 bot/其他租户兜底。
- 初始化未完整回读前保持 `unprovisioned`；该状态下不得创建定时任务、读取消息或写记录。

## 状态机

### 1. 建立私有配置

复制 `config.example.json` 到 `${EMOTION_TIDE_CONFIG:-~/.config/emotion-tide/config.json}`，权限设为 `600`。生成随机 UUID 写入 `installation_id`，填入用户选择的 `lark_profile`。Base 四个字段保持 `null`。

告知文本处理位置并取得同意后，才写入 `text_processing_consent=true`。

### 2. 绑定当前用户

执行用户身份验证，取实时 `openId`。把它同时写入 `owner_user_id` 与 `recipient_user_id`；后者只为兼容既有配置的身份绑定校验，绝不用于发送消息。支持 `auth status --json --verify` 的环境必须满足 `identity=user` 且 `verified=true`；当前 CLI 构建若没有 `auth` 子命令，可退回 `contact +get-user --as user` 解析当前用户。仅 `task +get-my-tasks` 这种 user-context canary 不能用于 owner 绑定。

运行：

```bash
python3 scripts/doctor.py --live --allow-unprovisioned
```

### 3. 创建全新 Base

使用配置中的 profile 和 `--as user` 调用 `base +base-create`。先运行 `provisioning_checkpoint.py prepare`：它从随机 `installation_id` 生成一个稳定且专属的可读名称，例如“情绪潮汐 · A1B2C3D4E5F6”，并把名称和启动时间写进仅本机可读的配置。初始表名为“每日情绪”，字段必须来自 `output-schema.md`，包括机器汇总、六维文本信号、本人表情回应和用户自评字段。

创建结果必须不落入聊天、日志或普通临时文件，直接流入检查点脚本：

```bash
BASE_NAME="$(python3 scripts/provisioning_checkpoint.py prepare --config "$EMOTION_TIDE_CONFIG" --emit base-name)"
lark-cli base +base-create --profile "<config profile>" --as user \
  --name "$BASE_NAME" --table-name "每日情绪" --fields '<schema JSON>' --json \
  | python3 scripts/provisioning_checkpoint.py bind --config "$EMOTION_TIDE_CONFIG"
```

`bind` 只接受 `identity=user` 的真实创建 envelope，并以原子替换写入本次返回的 Base URL/token 与 table ID；成功后仍是 `unprovisioned`，不等于完成初始化。它的标准输出不含坐标、身份或 token。

同一初始化流程继续创建仪表盘及组件，按 `dashboard-blocks.md`（块集 SSOT）尽量丰富地布置：置顶「最近总结」文本块（先放占位内容）与方法说明文本块；四张指标卡（记录天数、平均置信度、平均情绪强度、平均帮助程度）；趋势区（强度×置信度组合图、情绪强度趋势、文字表达活跃度、本人表情回应）；分布区（主情绪、覆盖质量、表情互动线索、用户校准）；六维状态轮廓雷达（只使用六个文本状态字段）；以及可选的辅助情绪词云。按顺序创建、不并行，全部创建后调用 `base +dashboard-arrange` 智能排布。所有图表只消费 `output-schema.md` 的既有字段，不新增 Base 字段。

创建「最近总结」文本块时，记录其返回的 `block_id`，写入配置 `base.summary_block_id`，供每日 `+dashboard-block-update` 幂等改写。

只使用本次创建调用返回的 Base token、table ID、dashboard ID。任何步骤失败都保留 `unprovisioned`，并向用户报告已创建但未完成的资源；禁止无界重试或静默创建第二套。

### 4. 回读归属与权限

依次证明：

1. Base owner 是刚验证的当前用户；
2. 直接协作者只有该用户一人；
3. 链接分享关闭；
4. 组织外分享关闭；
5. 表、字段、仪表盘及六维雷达真实存在。

权限读取受限时，让用户在飞书界面确认，不能提前进入 `ready`。

### 5. 提交 ready

把本次返回的 Base URL/token、table ID、dashboard ID 与「最近总结」文本块的 `summary_block_id` 写入私有配置，将 `provisioning_state` 改为 `ready`。运行完整 doctor：

```bash
python3 scripts/doctor.py --live
```

只有全部检查通过后，才进入开箱即用的季度盘点。创建 17:50 自动化前还要按 `conversation-delivery.md` 确认定时任务能回到本次用户对话且宿主提供 `present_files`；不能确认就不创建定时卡片投递，也不改用飞书私聊。

### 6. 季度盘点（开箱即用）

`ready` 且 `text_processing_consent=true` 后，按 `references/quarterly-backfill.md` 回填过去约一个季度的工作日记录，让新 Base 一开始就有趋势可看。前置硬门槛：实时用户=owner=配置中的身份绑定字段、回填窗口所有年份的官方工作日日历齐全。回填复用每日流程的同一套读取、聚合、校验和按日期幂等 upsert，串行带退避、可断点续跑，逐日不出图、不进行对话投递。回填全部完成后，按 `references/dashboard-blocks.md` 构建一次顶部「最近总结」文本块（读回最近若干天汇总字段 → `summarize_window.py` → 模型叙事 → `validate_summary.py` → `+dashboard-block-update`），再创建绑定本对话的 17:50 自动化，并按当天做一次正常的当日回顾。

## 重装与恢复

- 配置为 `ready`：先核验当前用户、owner 与 Base 可读性；全部匹配才复用。
- 配置为 `unprovisioned` 且已有部分 ID：先回读这些精确 ID，继续缺失步骤；不要重新创建。
- **有界恢复（仅创建响应在绑定前丢失时）**：仅当私有配置保留 `recovery_label`、`provisioning_started_at`，且 `python3 scripts/provisioning_checkpoint.py recovery-plan --config "$EMOTION_TIDE_CONFIG"` 在 60 分钟窗口内返回成功，才可对该专属标签做一次 `base +title-resolve`。只接受**唯一**且名称精确相等的候选；随后仍须用当前 profile + `--as user` 回读 Base owner、唯一初始表及完整字段指纹，并核验协作者、链接分享和组织外分享。任何候选数不等于一、名称不精确、owner/结构/权限不能证明或窗口过期时停止并请用户提供 URL；不得创建第二套，也不得读取消息或写记录。通过这些回读后，才把该候选的精确坐标写回私有配置并继续未完成的初始化。
- 旧版配置缺少 `provisioning_state`、`installation_id` 或显式 `owner_user_id`：完整 doctor 必须失败。先保留一份私密备份，再按 `unprovisioned` 处理，禁止根据已填写的 Base 字段推断为 `ready`。
- 判断身份时只认配置中的 `lark_profile` 及其实时 `openId`。默认 profile 只用于发现身份错配，不能用来接管、否定或替代配置身份。
- 旧版配置中的精确 Base ID 只有在配置 profile 可读、owner/历史身份绑定字段/live user 三者一致且权限回读通过时才允许迁移；遇到 `91403`、owner 不一致或来源无法证明时清空绑定并创建新 Base。
- 配置文件丢失，或没有有效的专属恢复标签：把它视为新安装。不得按“情绪潮汐”标题搜索并自动接管同名 Base；用户可显式提供自己原有 Base URL，再走归属与权限回读。
