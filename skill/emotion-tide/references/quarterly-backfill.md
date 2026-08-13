# 首次运行：过去一个季度的工作日盘点

## 目标

首次创建 Base 后，Base 是空的：只有连续多天运行才会积累出趋势和雷达。为了“开箱即用”，初始化通过后立即回填过去约一个季度（默认 90 天）的**工作日**记录，让仪表盘一开始就有可看的历史，而不是先等几周。

回填复用每日流程完全相同的规则：同一个工作日门禁、同一套去标识化聚合、同一份 schema 校验、同一个按日期幂等的 upsert。回填不是一条新的分析路径，只是把“分析一天”这件事，按日历倒着补齐历史工作日。

## 前置条件（硬性）

回填只能在满足以下全部条件后开始，任何一条不成立就不回填：

1. `provisioning_state=ready`，且完整 `doctor.py --live` 通过；
2. 当前实时用户身份 = Base owner = 通知接收人，三者一致；
3. `text_processing_consent=true`（回填会把历史消息文本交给已同意的处理位置）；
4. 覆盖回填窗口所有年份的可核验官方工作日日历都已配置（跨年时两年都要有）。

回填读取的是**用户本人历史消息**，与每日流程的隐私边界完全一致：只保留 `sender.id == 当前用户 ID` 的消息，正文只存在于进程内，Base/日志/图片都不落原文、聊天名、人员 ID、消息 ID。

## 日历要覆盖整个窗口

默认窗口是 `[as_of-90, as_of-1]`，可能跨年（例如 2 月运行会回看到上一年 11 月）。`workday_calendar` 支持两种写法，可同时使用：

- 旧版单年：顶层 `year/workdays/holidays`；
- 多年：`years: [{year, source_url, workdays, holidays}, ...]`。

窗口内任一天找不到对应年份日历，规划器把该天记为 `unknown` 并列入 `unknown_dates`，同时以退出码 `5` 表示日历不完整。此时应先补齐日历再回填，不要对 `unknown` 的日子猜测工作日状态。

## 流程

### 1. 规划（不联网、不读消息）

先获取 Base 中已存在的日期，避免重复写入并支持断点续跑。用 profile + `--as user` 读取“每日情绪”表的“日期”列，把去重后的 ISO 日期写入一个临时文件（JSON 数组或每行一个），例如 `$TASK_TMP/done-dates.json`。

再生成计划：

```bash
python3 scripts/backfill_plan.py \
  --config "$EMOTION_TIDE_CONFIG" \
  --as-of YYYY-MM-DD \
  --lookback-days 90 \
  --done-dates-file "$TASK_TMP/done-dates.json" \
  --limit 12
```

- `pending`：按时间**从旧到新**排序、仍需分析的工作日，每条含 `date`、`start`、`end`（本地日 `00:00` 到次日 `00:00` 的带时区窗口）。
- `counts`：总天数、工作日、非工作日、`unknown`、已存在天数、待处理数。
- `calendar_complete=false` 或退出码 `5`：日历不完整，先补日历。
- `--limit` 只返回最旧的 N 天，配合 Base 写入限流分批推进；不传 `--limit` 返回全部待处理日。

### 2. 逐日分析（串行）

对 `pending` 中每一天，按该天的 `start`/`end` 时间窗，执行与每日流程一模一样的步骤：

1. 用 profile + `--as user` 读取该窗口内用户可见消息与本人主动表情，检查分页；覆盖无法证明时把 coverage 降为 `partial`/`unavailable`。
2. 消息 JSON 通过 stdin 交给 `extract_reaction_signals.py`，参数 `--start`/`--end` 用该天窗口。
3. 去标识化后交模型生成 `output-schema.md` 的 JSON，`date` 必须是该天。
4. 通过 stdin 交 `validate_analysis.py`；失败最多重试一次，仍失败则跳过该天并记入回填汇报，不自由补字段。
5. 按日期幂等 upsert 到 Base，回读成功后再进入下一天。

**串行、带退避**：Base 写入是已知瓶颈，逐条写入并对限流做退避，不要并行批量写。每完成一天更新 `backfill.last_completed_date`，被限额或中断打断后可从下一天续跑。

### 3. 回填期间不打扰

回填是补历史，不是当天回顾：

- 默认 `backfill.render_per_day=false`、`notify_per_day=false`：逐日不发 PNG、不发暖心话、不发校准问题。历史某天证据不足属正常，按 schema 写入即可，不逐日通知。
- `attention_flag=human_attention` 只在分析当天（今日）回顾里触发安全语言；回填历史日**不**对旧消息升级危机、不做风险分级、不追溯发送安全干预。历史命中只在最终汇报里以“检测到 N 天历史命中人工关注标记，未对历史消息采取危机干预”一句说明，供用户自行查看。
- 无本人消息的工作日按 `无本人消息` 正常写入，保持趋势连续，不发通知。

### 4. 收尾

全部 `pending` 处理完（或达到本次 `--limit` 批次上限）后：

1. 更新 `backfill.state`（`in_progress` / `completed`）与 `last_completed_date`；
2. 若 `remaining_after_limit>0`，说明还有更旧或后续批次未做，告知用户可再次运行继续；
3. 回填完成后再进入常规每日流程，并按当天做一次正常的“当日回顾 + PNG + 校准问题”。

## 汇报口径

向用户汇报真实结果，不要假设成功：窗口范围、工作日总数、已写入天数、本次新增天数、跳过天数（校验失败/读取失败）及原因、剩余待处理天数、日历是否完整、历史人工关注命中数。写入 Base 的记录必须回读确认后才算完成。
