# 当天卡片

Base 仪表盘负责长期趋势与六维雷达；PNG 只负责当天回顾，不重复绘制雷达。飞书 CLI 没有稳定的 Base 仪表盘截图接口，因此图片由同一份已校验 JSON 在本地生成，不能冒充飞书页面截图。

```bash
TASK_TMP=$(mktemp -d)
python3 scripts/render_dashboard.py --output "$TASK_TMP/emotion-tide.svg" < analysis.json
sips -s format png "$TASK_TMP/emotion-tide.svg" --out "$TASK_TMP/emotion-tide.png"
```

渲染器只接收汇总字段。动态文字使用保守测宽、换行、省略号和 SVG 裁切。Base 当天记录回读成功后，由宿主对话的 `present_files` 按该运行时的工具参数传入 PNG 的绝对路径；不得经飞书私聊发送。只有该调用返回后才能删除本次临时目录。
