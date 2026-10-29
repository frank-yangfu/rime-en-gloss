# 五笔常用词补全（骑行 / 车店 这类打不出来的词）

老版 `wubi86.dict.yaml`（ibus-table 词库）只收了约 15 万条词，现代常用词覆盖不全：

| 输入 | 旧结果 | 期望 |
|---|---|---|
| `cdtf` | 参选 / 参赞 | 骑行 |
| `lgyh` | （没有词条） | 车店 |
| `ymqr` | （没有词条） | 高铁 |

这不是拼音分栏的 bug：`cdtf` 里根本没有「骑行」这一条，`lgyh` 里一条都没有。
解决办法是给基础词库加一层**补充词库** `wubi86.extended.dict.yaml`（导入 `wubi86`）。

## 一、直接用预生成的补全词典（推荐）

v1.4.0 Release 附件提供 `wubi86.extended.dict.yaml`（约 68,000 条补充词条）：

1. 下载并放到 Rime 用户目录（与 `wubi86.dict.yaml` 同目录）；
2. 在方案补丁里指向它：

   ```yaml
   # wubi_pinyin.custom.yaml
   patch:
     translator/dictionary: wubi86.extended
   ```

3. 重新部署（改 YAML 必须部署；lua 不需要）。

扩展词库 `import_tables: [wubi86]`，所以基础词条原样保留，只增加词条。

## 二、自己生成

`tools/build_wubi_words.py` 从任意中文词表生成补全词典：

```bash
python tools/build_wubi_words.py \
    --wubi-dict "%APPDATA%\Rime\wubi86.dict.yaml" \
    --words     words.txt \
    --extra     data/wubi_words_extra.txt \
    --out       "%APPDATA%\Rime\wubi86.extended.dict.yaml"
```

- `--words`：一行一个词（可重复传入多个文件；项目的 `cache.txt` 也能直接用，
  会自动取第一列）；
- `--weights-file`（可选）：`词<TAB>权重`，用于按自己的频率表排序；
- `--extra`：手写词条，格式同 Rime 词典（`词<TAB>码<TAB>权重`），重跑不会丢；
- 词码自动计算：
  - 2 字词：AaAbBaBb（骑行 = 骑 lg + 行 tf → `cdtf`）
  - 3 字词：AaBaCaCb
  - 4 字及以上：AaBaCaZa

### 权重怎么定

- 当前编码**没有词条** → 给 `--low`（默认 100 万）：先让词可选到，不抢别人的位置；
- 当前编码最强词条**较弱**（< `--floor`，默认 500 万）→ 给 `--floor`：让普通词压过冷僻词；
- 当前编码已有**强词条** → 跳过（保持基础词库排序），`--include-strong` 可强制也加。

## 三、加自己的词

最简单的方式是加到 `data/wubi_words_extra.txt`（或你自己的 extra 文件）：

```
骑行	cdtf	50000000
车店	lgyh	50000000
```

然后重新跑 `build_wubi_words.py`（`--extra` 传入该文件）。权重给 5000 万通常足够
压过同码的普通词。

也可以直接往 `wubi86.extended.dict.yaml` 手动加一行，但重跑生成器会覆盖，建议用 extra 文件。

## 四、配套：拼音只认全拼（可选，推荐五笔用户开启）

混输方案里，拼音简拼（首字母缩写，如 `nh` → 你好）和三/四字母五笔码容易混淆。
如果希望**只有完整拼音才出拼音候选**，在 `pinyin_simp.custom.yaml` 里不要挂
`pinyin:/abbreviation`：

```yaml
# pinyin_simp.custom.yaml
patch:
  speller/algebra:
    __patch:
      - pinyin:/spelling_correction
      - pinyin:/key_correction
      - pinyin:/zh_z_bufen
      - pinyin:/n_l_bufen
      - pinyin:/hu_f_buhun
      - pinyin:/en_eng_bufen
      # 不加载 pinyin:/abbreviation —— 只认全拼
```

效果：`nh` / `nj` 这类缩写不再出拼音（走五笔），而 `nihao`、`beijing`、
`zhongguo`（以及模糊音 `zongguo`）仍然正常。重新部署后生效（prism 会重建）。
