# T13 错误归因与定性挑战集

2026-10-30；用户确认直接实施，不使用 OpenSpec。用户确认 line15 主归因为 `character_recognition`，手稿范围为离线定性两行。

## 变更点

- 建立 `line_detection`、`character_recognition`、`unicode_mapping`、`unknown_or_mixed` 四类互斥主归因及证据契约。
- 主评测案例固定为 line15 的 U+11235 insertion；绑定 T12 对齐、冻结原始预测、人工真值、裁剪和检测记录，不声称不存在的字符级像素框。
- 第 9 页固定两个定性检测案例：独立非文字候选 `p0009-l010-9eee9db3825d`，以及过宽/重叠候选 `p0009-l009-99b5a8f5d214`。不计算无人工框支持的 precision、recall、IoU 或检测 CER 差值。
- 从来源标为手稿的第 1–6 页离线处理并选择两条不同页面的正文候选；保存裁剪、来源和哈希，不转录、不生成真值、不计算 CER。
- 新增可复算错误分析 CLI、严格证据哈希和结构化产物；T12 主 CER 保持不变，所有挑战案例排除于主指标。
- 生成英文 T13 报告并回填 task、plan、README；零 API 调用、零新增费用。

## 测试计划

- 拒绝未知标签、重复案例、缺失证据、证据哈希错误、空理由和非法范围。
- 验证 line15 绑定唯一 U+11235 insertion、原始预测和冻结真值，主标签必须为 `character_recognition`。
- 验证第 9 页两个案例绑定固定 400 DPI detection run，且不进入 CER。
- 验证手稿恰有两行、来源为第 1–6 页、无 prediction/reference/CER 字段且不进入主指标。
- 禁止网络/API 客户端；相同输入核心 JSON 可重复；产物支持独立完整性验证。
- 完整 pytest、pip check、T12 verify，以及预算、真值、缓存和 selection 来源保护哈希复核。

## 假设与风险

- 当前目录不是 Git 仓库，不初始化 Git 或同步 Gitee。
- 唯一主错误不足以形成稳定错误分布；只能称为唯一观察到的错误。
- `unicode_mapping` 为零表示本十行没有已确认案例，不等于该风险不存在。
- line15 没有字符级图像坐标；模型 uncertainty 是文本 offset，报告不得把它画成精确 glyph box。
- 第 9 页没有完整人工框，只能作为定性检测证据。
- 手稿没有人工转录，不能报告识别准确率或 CER；若检测器不能给出两个可信正文候选，暂停请用户选择而不是使用装饰物。

### 已核对的范围调整

联系表视觉复核发现第 1 页候选左边界不完整，尽管 detector 无 flags。用户明确选择“接受失败案例”，同意调整最初“不选明显截断行”的要求，将该行作为手稿检测失败的定性案例；第 5 页候选保留 ambiguous_mark/overlapping_line_content 局限。两行均不转录、不生成真值、不计算 CER。

## 执行结果总结

- 正式分析包 `outputs/20261030T233828Z-bdf49aab235d/`，包括五个案例（1 主错误、2 检测、2 手稿）、汇总 JSON、英文报告、三张证据图和来源/产物哈希。
- line15 主归因为 `character_recognition`，核对原始预测、真值、图像、唯一 U+11235 insertion 和模型 `[21,22)` 疑似标记；其余主类别为 0，未确认映射错误不虚构案例。
- 手稿 300 DPI 预处理 `outputs/20261030T230939Z-421e14dcddd6/`，检测 `outputs/20261030T230955Z-e8f041782050/`，第 1–6 页共 194 个几何候选。挑战集 `data/challenges/t13/frozen/` 保存第 1 页 l004、第 5 页 l020 两行，第一行左截断经用户确认作为失败案例保留。
- 实现 `error_analysis.py`、`build-challenge-set`、`analyze-errors`、`verify-error-analysis`；冻结非覆盖且使用临时目录发布，核心输出可重复，证据和 T12 冻结来源可独立复验。
- 完整测试 234 passed（新增 12 项归因/挑战集测试），7 条既有 SWIG 弃用警告；pip check 正常。T13/T12 verify 均通过。预算账本、真值、真值指针、T12 manifest 前后哈希一致；T11 来源保护清单覆盖预测、缓存和 selection，均未改变。
- 主 CER 保持 `1/253 = 0.003952569170`；T13 API 调用 0，新增费用 USD 0。已回填 task、plan、README 和英文 `reports/t13-error-analysis.md`。

## 后续跟进

- T14 将 T12 指标和 T13 分阶段证据整合进英文交付文档与一页复盘。
