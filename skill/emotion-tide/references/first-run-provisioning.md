# 首次运行：每位用户独立创建 Base

## 不变量

- 一个 `installation_id` 只绑定一个已验证飞书用户和一套 Base。
- Base owner、通知接收人、消息读取主体必须是同一个当前用户。
- 公开仓库与示例配置只含 `null`，不提供任何可连接的 Base、用户或租户标识。
- 禁止复制维护者 Base、复用其他用户 token、按同名标题猜测 Base，或切换 bot/其他租户兜底。
- 初始化未完整回读前保持 `unprovisioned`；该状态下不得创建定时任务、读取消息或写记录。

## 状态机

### 1. 建立私有配置

复制 `config.example.json` 到 `${EMOTION_TIDE_CONFIG:-~/.config/emotion-tide/config.json}`，权限设为 `600`。生成随机 UUID 写入 `installation_id`，填入用户选择的 `lark_profile`。Base 四个字段保持 `null`。

告知文本处理位置并取得同意后，才写入 `text_processing_consent=true`。

### 2. 绑定当前用户

执行用户身份验证，取实时 `openId`。把它同时写入 `owner_user_id` 与 `recipient_user_id`。支持 `auth status --json --verify` 的环境必须满足 `identity=user` 且 `verified=true`；当前 CLI 构建若没有 `auth` 子命令，可退回 `contact +get-user --as user` 解析当前用户。仅 `task +get-my-tasks` 这种 user-context canary 不能用于 owner 绑定。

运行：

```bash
python3 scripts/doctor.py --live --allow-unprovisioned
```

### 3. 创建全新 Base

使用配置中的 profile 和 `--as user` 调用 `base +base-create`，名称为“情绪潮汐”，初始表名为“每日情绪”。字段必须来自 `output-schema.md`，包括机器汇总、六维文本信号、本人表情回应和用户自评字段。

同一初始化流程继续创建仪表盘及组件：记录天数、平均置信度、情绪强度趋势、文字表达活跃度趋势、本人表情回应趋势、主情绪分布、六维状态轮廓和方法说明。雷达只使用六个文本状态字段。

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

把本次返回的 Base URL/token、table ID、dashboard ID 写入私有配置，将 `provisioning_state` 改为 `ready`。运行完整 doctor：

```bash
python3 scripts/doctor.py --live
```

只有全部检查通过后才创建 17:50 自动化。

## 重装与恢复

- 配置为 `ready`：先核验当前用户、owner 与 Base 可读性；全部匹配才复用。
- 配置为 `unprovisioned` 且已有部分 ID：先回读这些精确 ID，继续缺失步骤；不要重新创建。
- 旧版配置缺少 `provisioning_state`、`installation_id` 或显式 `owner_user_id`：完整 doctor 必须失败。先保留一份私密备份，再按 `unprovisioned` 处理，禁止根据已填写的 Base 字段推断为 `ready`。
- 判断身份时只认配置中的 `lark_profile` 及其实时 `openId`。默认 profile 只用于发现身份错配，不能用来接管、否定或替代配置身份。
- 旧版配置中的精确 Base ID 只有在配置 profile 可读、owner/recipient/live user 三者一致且权限回读通过时才允许迁移；遇到 `91403`、owner 不一致或来源无法证明时清空绑定并创建新 Base。
- 配置文件丢失：把它视为新安装。不得按“情绪潮汐”标题搜索并自动接管同名 Base；用户可显式提供自己原有 Base URL，再走归属与权限回读。
