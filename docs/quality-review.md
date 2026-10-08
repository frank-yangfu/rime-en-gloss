# 译义质量审查记录

对整张对照表（约 12 万条 → 重审后 96k 条）做过一次全量审查，结论与修法记录在此。

## 一、两个系统性根因

### 1. 机器翻译生成的 13,071 条垃圾条目

早期版本用神经网络模型给词典没收的词补译文，结果模型把**词片段**当成句子翻译：

| 词 | 生成的英文 |
|---|---|
| 人不 | No, no, no |
| 一大 | A big one |
| 就能 | Yeah |
| 我的 | Mine |
| 我人口不 | I'm not a population |
| 不可不 | I'm sure of it |

这些条目被缓存逻辑固化下来。现在：

- 全部剔除；
- 模型**只允许处理 3 字以上**的词；
- 输出还要过一层句式过滤（首字母大写、含人称代词、含 `!?.` 或逗号、超过 8 个词一律丢弃）。

宁可这一行没有英文，也不显示错误英文。

### 2. CC-CEDICT 的多音词条顺序

词典按读音分条，常用读音常排在后面，取第一条就取到冷僻义：

| 词 | 取到的义项 | 应取 |
|---|---|---|
| 告诉 | to press charges（gào sù，起诉） | to tell; to inform |
| 东西 | east and west | thing; stuff |
| 结果 | to bear fruit | result; outcome |
| 一次 | first | once; one time |
| 活动 | to exercise; to move about | activity; event |

另有 **3,072 条**条目内容只有 `variant of 繁體|简体`，导致简体词取不到释义
（联系 / 发布 / 这里 因此一度被模型顶替成 Contact / Release / Here）。

## 二、修法

### 1. 变体链解析

`variant of 聯繫|联系[lián xì]` → 取其中的（繁/简）词形继续查，最多递归三层。
这一步单独解决了上千条常用词。

### 2. 常用度打分选义

每个候选义项用 ~600 个最常用英语词打分（覆盖率 − 长度惩罚），取分最高者：

```
告诉  → "to tell" (1.00)  打败 "to press charges; to file a complaint" (0.43)
球    → "ball"            打败 "ball used for playing games"
叶    → "leaf"            打败 "to be in harmony"
```

同时：义项超过 40 字符时**只取第一个分句**，这样成语不会因为太长被整条丢掉
（烟消云散 → *to vanish like smoke*）。

### 3. 人工校准表

| 表 | 条数 | 覆盖 |
|---|---|---|
| `SINGLE` | 1,557 | 逐条审查前 1,200 高频单字：语气词（吧/吗/呢）、虚词（之/其/并）、量词（个/只/张）、姓氏、部首义、文言义 |
| `WORD` | 638 | 高频词组与成语（画蛇添足 / 亡羊补牢 / 守株待兔…） |
| `COLLOQUIAL` | 155 | 词典未收录的口语词（都是 / 就能 / 很多 / 我的 / 两个） |
| 地名国家 | 98 | 广州 / 深圳 / 杭州…；香港、澳门、台湾按规范标注（Hong Kong, China 等） |
| `SURN` | 340 | 姓氏字，词典只有姓氏义时输出 `(surname X)` |
| `overrides_legacy.json` | 586 | 早期审查积累 |

优先级：`SINGLE`/`WORD` > `overrides_legacy.json` > 词典选义。改错了直接改回即可。

### 4. 噪音过滤

不收录：部首说明（*Kangxi radical 118*）、交叉引用（*variant of / see also / same as*）、
学说与人名条目（*essay by … philosopher …*）、拉丁学名（*Torreya nucifera*）、
被截断的残句、繁体单字（後 / 於 / 徵 / 麽）。

## 三、修正效果（节选）

| 词 | 修正前 | 修正后 |
|---|---|---|
| 打 | dozen | to hit; to play |
| 告诉 | to press charges | to tell; to inform |
| 东西 | east and west | thing; stuff |
| 结果 | to bear fruit | result; outcome |
| 一次 | first | once; one time |
| 篇 | sheet | article; chapter |
| 电 | lightning | electricity |
| 局 | narrow | bureau; situation |
| 离 | mythical beast | to leave; apart |
| 士 | member of the senior ministerial class | scholar; person; soldier |
| 刘 | a type of battle-ax | (surname Liu) |
| 潘 | water in which rice has been washed | (surname Pan) |
| 圣 | to dig with persistent effort | holy; saint |
| 药 | to poison | medicine |
| 喝 | oh | to drink |
| 读 | phrase marked by pause | to read |
| 环境 | ambient | environment; surroundings |
| 寂寞 | quiet | lonely; lonesome |
| 就能 | Yeah | then one can |

## 四、最终构成

```
96,443 条  =  1 字 5,863  +  2 字 55,535  +  3 字 18,768  +  4 字 16,277
机器翻译条目：0
```

## 五、待办

- 第 1,200–5,900 位的单字尚未逐条人工过目（目前已由选义算法 + 噪音过滤兜底）。
- 也可以换成更权威的现代汉语词表来替代 CC-CEDICT 的单字释义。
- 欢迎直接提 PR 修改 `tools/glossary.py` 里的表项，附上「词 / 现有译文 / 建议译文」即可。
