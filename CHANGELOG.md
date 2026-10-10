# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-10-10

### 修复

- **打人名只上屏第一个字（如 lilinfei 只出「李」，后面的编码被吞掉）**：
  filter 重建候选时用 `Candidate("table", 0, #code, ...)` 把每条候选的输入区间
  写成「从 0 到整句编码长度」。拼音连续输入（`li|lin|fei` 分段组句）和五笔连打
  的候选原本各自只覆盖自己那一段，被改写后选择任何一条都会把**整个编码**一起
  提交——选「李」后剩余编码直接消失，打不出「林菲」。五笔方案挂在同一个
  filter 上（`enable_sentence: true` 开启组句），同样受影响。
  现改用 `ShadowCandidate` 包裹原候选：只替换注释、完整保留原候选的输入区间。
  当 librime-lua 未提供 `ShadowCandidate` 时保持原候选不变（缺英文注释好过
  组句被破坏）。已用真实 Lua 运行时（lupa）模拟多段组合验证：
  选「李」后编辑器内保留 `nfei` 继续组句，旧实现则清空全部编码。
  `tools/selftest.py` 新增对应回归断言。
- **输入体验**：`default.custom.yaml` 示例新增 Shift 直接上屏原始输入
  （`ascii_composer/switch_key/Shift_L: commit_code`），打英文时按 Shift 即上屏，
  不必再按回车（连按回车容易把消息直接发送出去）。

## [1.0.0] - 2026-10-08

首个公开版本。

### 新增

- `lua/input_text.lua`：Rime candidate filter，把英文写入候选注释槽，格式统一为 `编码, 英文`。
  - 增量读取词表（每次按键 ≤ 4 万行）、只在缓存未命中时读盘、每秒最多读一次。
  - 只检查前 30 个候选，其余原样透传；不在输入线程里启动任何进程。
- `tools/glossary.py`：释义挑选算法 + 人工校准表。
  - 解析 CC-CEDICT 的 `variant of 繁體` 链（3,072 条受益）。
  - 用 ~600 个常用英语词给每个义项打分，取最日常且最短的（修正多音词条取到冷僻义的问题）。
  - 超过 40 字符的义项只取第一个分句，避免成语被整条丢弃。
  - 人工校准：单字 1,557 条、词组 638 条、口语词 155 条、地名国家 98 条、姓氏 340 字。
  - 噪音过滤：部首说明、交叉引用、学说/人名条目、拉丁学名、截断残句、繁体单字。
- `tools/build_cache.py`：纯标准库构建脚本，按「五笔词频 / 拼音词频 / 字频」三路排名排序。
- `tools/fetch_cedict.py`：下载并转换 CC-CEDICT 为 JSON。
- `tools/optional_mt_server.py`：可选的离线模型服务，用于 3 字以上长尾词；模型输出需通过句式过滤。
- `schema/add_filter.patch.yaml`、`scripts/install.ps1`、`scripts/start_helper.bat`、`scripts/start_helper_hidden.vbs`。
- 文档：`docs/how-it-works.md`、`docs/quality-review.md`、`docs/troubleshooting.md`。

### 修复（发布前第二轮全量审查）

- **自引用变体导致 244 个常用字缺失**：CC-CEDICT 存在 `妙 -> variant of 妙`、`埋 -> used in 埋怨`
  这类空壳词条，覆盖了正常释义，导致 妙/吻/埋/借/凡/仙/农/丐/匙/凳… 取不到英文。
  解析改为**合并同一词的全部词条**（去重、保持顺序），并跳过指向自身的变体链。
- **专有名词义项抢占**：合并后专有名词条目变得可见，`比萨 -> Pisa, town in Toscana, Italy`、
  `大拇指 -> Tom Thumb`、`标致 -> Peugeot`、`密 -> name of an ancient state`。
  新增降权规则：非白名单的大写词每个 -0.35，地名/朝代/人名式短语再 -0.4（降权而非删除，
  保证 `唐朝 -> Tang dynasty` 这类唯一释义仍能显示）。
- **单字写进 `WORD` 表会被静默忽略**：`refine_char` 现在同时查 `SINGLE` 和 `WORD`。
- 修正一批具体译义：塔 tower; pagoda、甚 very; extremely、采 to pick、便便 poo、佃 to rent land、
  台风 typhoon、国政 national politics、大陆 mainland China、官话 Mandarin 等。
- **记录一次失败的优化**：把常用英语词表从 422 扩到 679 会改动约 3% 的词条，有升有降
  （分店 annex→branch 变好，便便 poo→obese 变坏），已撤回并在 `glossary.py` 中注明原因。

### 质量

- **移除全部 13,071 条机器翻译生成的条目**（曾产出 `人不 → No, no, no`、`就能 → Yeah` 之类）。
  模型现在只处理 3 字以上的词，且要过一层句式过滤。
- 修复「英文永远不显示」：librime-lua 的候选对象没有 `end` 属性，构造方式已改为固定参数。
- 修复「宿主程序卡死」：去掉大字典 `require`、去掉 `os.execute`、限制只遍历前 30 个候选。
- 词表最终 96,784 条（1 字 6,123 / 2 字 55,591 / 3 字 18,772 / 4 字 16,298），约 2.4 MB。
- 新增 `tools/selftest.py` 与 CI 工作流：把审查期发现过的 bug 固化成断言，防止回退。
