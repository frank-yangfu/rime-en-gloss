# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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

### 质量

- **移除全部 13,071 条机器翻译生成的条目**（曾产出 `人不 → No, no, no`、`就能 → Yeah` 之类）。
  模型现在只处理 3 字以上的词，且要过一层句式过滤。
- 修复「英文永远不显示」：librime-lua 的候选对象没有 `end` 属性，构造方式已改为固定参数。
- 修复「宿主程序卡死」：去掉大字典 `require`、去掉 `os.execute`、限制只遍历前 30 个候选。
- 词表最终 96,443 条（1 字 5,863 / 2 字 55,535 / 3 字 18,768 / 4 字 16,277），约 2.4 MB。
