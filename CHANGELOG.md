# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.5.1] - 2026-10-29

### 修复

- **单字母输入短码不对**：`o` 出「噢」而不是「为」（`a` 同理应出「工」）。现规定
  **单字母按五笔一级简码优先**（`o`→为、`a`→工、`e`→有），拼音候选退到后面/不再出现。
- **`wq` 只出「你」**：v1.5.0 推荐关闭五笔补全（`translator/enable_completion: false`）
  过度修正，短码补全全没了。恢复默认补全，`wq` 重新出现 你 / 低 / 像 / 爸 / 爷 / 釜 …。
- **大词库下拼音被补全挤掉**：过滤器头部候选上限 200 → **1000**，`shi` 等拼音输入
  不再被成百上千条补全埋掉（实测 `shi` → 是 / 时 / 事 …）。

### 说明

- v1.5.0 的扩展词库、混排模式、`wubi_override.txt` 均保留不变；
- 若你更喜欢干净菜单，仍可手动设 `translator/enable_completion: false`，但短码补全会消失。

## [1.5.0] - 2026-10-29

### 新增

- **五笔词优先混排**：输入既能切拼音、又正好是五笔词码时，不再二选一——五笔词排前面，
  拼音候选跟在后面（`tade` → 长有 / 他的；`aiyi` → 东京 / 爱意；`guge` → 平静 / 谷歌）。
  单字冲突仍由 `lua/wubi_override.txt` 处理（`yaa` 只出「试」）。
- **扩展词库 v2**：Release 附件 `wubi86.extended.dict.yaml` 扩充到约 **147,000** 条
  （3.2 MB），补齐二字/三字常用词：`异响`（nakt）、`扫码`（rvdc）、`高铁`（ymqr）等。
- **过滤器头部候选上限 30 → 200**：避免大词库把拼音候选挤出模式判定范围。
- **文档**：`docs/wubi-words.md` 增加混排模式、关闭三/五笔补全 (`translator/enable_completion: false`)
  的推荐配置，以及更多示例。

### 修复

- 2/3 字词用五笔打却出拼音（`tade`、`guge`、`aiyi` 等）或打码不出的问题；
- 大词库下 `shi` 这类拼音输入被成百上千条五笔补全挤到后面（关闭补全 + 混排后恢复）。

## [1.4.0] - 2026-10-29

### 新增

- **五笔常用词补全词典**：Release 附件 `wubi86.extended.dict.yaml`（约 68,000 条补充词条，
  导入基础 `wubi86` 词库）。修复 `骑行`（cdtf）、`车店`（lgyh）、`高铁`（ymqr）这类
  “词库缺词、码打不出目标词”的问题。
- **`tools/build_wubi_words.py`**：从任意中文词表生成补全词典，自动按
  AaAbBaBb / AaBaCaCb / AaBaCaZa 计算五笔词码；支持 `--weights-file` 权重表与
  `--extra` 手写词条（人名/个人词汇），重跑不丢。
- **`tools/build_wubi_words.py` 配套文档 `docs/wubi-words.md`**：原理、生成方法、
  个人词条添加，以及「拼音只认全拼」的推荐配置（移除 `pinyin:/abbreviation`）。

### 说明

- lua 插件、`lua/wubi_override.txt`、释义 `cache.txt` 均无变化；补全词典是可选的
  （不装不影响现有功能）。
- 词典/方案 YAML 改动需要重新部署 Rime（lua 改动仍只需重启服务）。

## [1.3.2] - 2026-10-23

### 修复

- **五笔码被当成拼音**（`yaa` 只出「鸭啊」、`eee` 出「饿饿饿」、`aqi` 出「阿奇」）：
  1.3.0 的模式判定把「能完整切成拼音音节」当作拼音，但 `yaa`（试）= `ya`+`a`、
  `nudu`（买）= `nu`+`du` 这类合法五笔码也满足条件，五笔候选被整体过滤掉。
  新增 `lua/wubi_override.txt`（1,122 码）运行时白名单：命中后在拼音切分之前强制走五笔。
- **纯五笔/纯拼音方案的尾段被截断**：所选模式一个候选都没有时（例如纯五笔方案没有拼音
  translator），尾段不再按模式过滤，菜单不会只剩前 30 条。

### 新增

- `lua/wubi_override.txt`、`tools/gen_wubi_override.py`、`tools/pinyin_keep.txt`：
  白名单数据与离线生成器。入表条件：能切拼音音节、本身不是拼音音节、不在精选拼音词表、
  且拼音词典同拼写最大权重 < 1000。重跑幂等，附带统计报告。
- `scripts/install.ps1` 会一并拷贝 `wubi_override.txt` 与 `pinyin_keep.txt`。

### 验证

- 1,122 个白名单码逐个输入：字符集内可用的 **810 个码 100% 首项命中**（修复前 7/1,122）；
  312 个 CJK 扩展区生僻码受 `extended_charset=常用` 限制，开「增广」即可。
- 200 个未入表的碰撞码与修复前完全一致；释义与性能无退化（单键中位 3.75 ms）；
  删掉白名单可整体回退旧行为。

### 升级

替换 `lua/input_text.lua`，并把 `lua/wubi_override.txt` 放到同一个 `lua/` 目录，然后
重启输入法服务（lua 改动无需重新部署）。释义词表无变化。

## [1.3.1] - 2026-10-21

### 修复

- **打一级简码出错字**（如 `g` 出「开」而不是「一」）：`user_table` / `user_phrase`
  两类候选被 1.3.0 的模式过滤当成噪声丢掉了。它们分别是**五笔**和**拼音**的用户词库条目：
  librime 把"词典里的"和"学进用户词库的"标成不同 type：

  | type | 含义 |
  |---|---|
  | `table` / `completion` | 五笔词典 / 五笔补全 |
  | `user_table` | **五笔用户词库**（学会的字词）|
  | `phrase` | 拼音词典 |
  | `user_phrase` | **拼音用户词库** |

  用户一旦把「一」打过若干次，它就从 `table` 变成 `user_table`；1.3.0 的过滤器把它丢掉，
  于是候选首位变成补全候选「开」。现按模式分别接受 `user_table`（五笔）与
  `user_phrase`（拼音）。
- **单字母输入没有英文注释**：`MIN_CODE_LEN` 被设成了 2，单字母输入直接跳过查词。
  改回 1，一级简码（`g`→一 [g, one]、`q`→我 [q, I; me]）现在都带英文。

### 验证

26 个一级简码 `a`~`y` 全部命中正确字且带英文注释；五笔词组、拼音词组、人名均正常。

## [1.3.0] - 2026-10-21

### 新增

- **五笔与拼音候选分离**：打五笔码只出五笔候选，打拼音才出拼音候选，不再混排。
  实现依据 librime 给每个候选标注的 `type` 字段：`table`/`completion` 是五笔，
  `phrase` 是拼音，`sentence`/`reverse_lookup` 是噪声（一律丢弃）。
  输入模式判定：输入串能完整切分为合法拼音音节 → 拼音模式；否则若有五笔 table
  候选 → 五笔模式。内置 421 个音节的记忆化切分，单次远低于 1ms。

  实测：

  | 输入 | 结果 |
  |---|---|
  | 五笔 `wqiy` | 你、仰泳 |
  | 五笔 `trnt` | 我、特性（拼音噪声「瘫软了」消失） |
  | 拼音 `nihao` | 你好、利好 |
  | 拼音 `tangping` | 躺平、烫平（五笔噪声「彻悟这渥」消失） |

- 人名扩展词库中的词条补上注释（如 杨满钊 -> (personal name)）。

### 修复

- **组句噪声**：`translator/enable_sentence: false`，消除把拼音码硬拼成句子的候选。
- **反查噪声**：移除 `reverse_lookup_translator`——它经 `abc_segmentor/extra_tags`
  对所有输入生效，产出 quality=0 的无意义候选。

## [1.2.0] - 2026-10-20

### 修复

- **英文注释中的俚语义项抢占常用义**（选义算法缺陷）：
  `草 -> to fuck`、`巨龙 -> big dick`、`鸡年 -> Year of the Cock`、`公鸡 -> cock; rooster`、
  `滚开 -> ...fuck off`、`杂种 -> son of a bitch`、`种禽 -> cock`、`杨 -> alder tree`。
  这些俚语义项**又短又由常用词构成**，`_score()` 反而给高分。
  新增 `VULGAR_DEF` 俚语词表 + `_vulgar_penalty()` 降权（**降权不删除**，
  词本义就是俚语的仍保留原义）。实测：草 -> grass、巨龙 -> giant dragon、
  杂种 -> hybrid、滚开 -> get out; go away、杨 -> poplar; surname。
  另补人工校准（SINGLE/WORD 表）。
- **超长释义被整条丢弃**：`best_gloss` 对 >40 字符且**无分号**的释义直接丢弃，
  导致知名词条取不到英文：`一带一路`（释义 90 字符）、`中国人民解放军`（85 字符）。
  改为按逗号取首段 + 词边界兜底。实测：一带一路 -> Belt and Road Initiative、
  中国人民解放军 -> People's Liberation Army。
- **候选注释里的粗俗英文改为中性写法**（47 条）：保留 `(vulgar)`/`(derogatory)` 标注，
  词义仍诚实，但屏幕上不再出现脏字本身。例：傻逼 -> (vulgar) idiot、
  婊子 -> (vulgar) prostitute、肏 -> (vulgar) to have sex、屁民 -> (derogatory) ordinary people。
  （石台县 -> Shitai 是安徽真实县名、迪克 -> Dick 是人名、张王李赵 -> any Tom, Dick or Harry
  是英语习语，均属合理保留，未改。）

### 新增

- `tools/build_pinyin_exp.py`：从 CC-CEDICT 构建扩充拼音词库（145,480 条，≥5 字长词 5,079 条），
  纯标准库、幂等、写后自检非 NUL。
- `tools/build_pinyin_simp_merged.py`：三层合并构建（原词库 + CC-CEDICT + 万象拼音），
  产出 151 万条词库（≥5 字长词 15.9 万条）。
- 保守剥离法：`自己的 -> oneself`（剥"的"）、`公司的 -> company; firm`。
  只剥离语义等价的 `的/们/地/得`，不剥 `了/着/过/不/没`（会改变语义）。
  **放弃**机械拼接单字释义（质量太差：`自己的 -> self + self + of`）——宁可不给，也不给错的。

### 说明

- 英文词表 96,991 -> **111,456 条**；字典序改为**单字优先**（多字词权重原会把单字挤到 7 万位之后，
  实测 `草` 从第 70,564 位提升到第 439 位）。
- 词表读取仍保持分批（`MAX_LINES_PER_CALL: 40000`，0.142s）：实测一次读 11 万行需 0.475s，
  在宿主输入线程中会造成明显卡顿，故不采用。
- 约 6.5 万条 CC-CEDICT 未收录的口语组合词（如果你/我觉得）仍无英文，属词典边界。

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