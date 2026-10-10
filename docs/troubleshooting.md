# 排障

先确认三件事，90% 的问题能定位：

```
1. 词表存在吗      %TEMP%\rime_argos\cache.txt      （应该有约 10 万行）
2. 过滤器挂上了吗  方案里是否有 lua_filter@*input_text*filter
3. 插件报错了吗    设 RIME_EN_GLOSS_DEBUG=1，看 %TEMP%\rime_argos\filter_debug.log
```

> Weasel 的日志在 `%LOCALAPPDATA%\Temp\rime.weasel\`，文件名含 `.ERROR.` 的那些是运行时报错。

---

## 完全没有英文

**1. 过滤器没生效**

lua 改动只需重启 `WeaselServer.exe`；schema 改动必须重新部署：

```powershell
taskkill /f /im WeaselServer.exe
& "$env:ProgramFiles\Rime\weasel-0.17.4\WeaselDeployer.exe" /deploy
Start-Process "$env:ProgramFiles\Rime\weasel-0.17.4\WeaselServer.exe"
```

`WeaselDeployer.exe /deploy` 长时间不返回，通常是被残留实例占用：先杀
`WeaselDeployer.exe` 再重试。改了 schema 却连编译产物都没更新时，直接删掉
`<Rime user dir>\build\` 强制全量重建。

**2. 词表没生成**

```bash
cd tools && python fetch_cedict.py && python build_cache.py
```

**3. 只显示编码、没有英文**

说明该词确实不在表里（生僻词、口语长词）。这是预期行为——宁可空着也不显示错译。
想要覆盖长尾词就启用[可选模型服务](README.md#可选长尾词离线补全)。

---

## 只有少数词有英文

词表是**按使用频率排序**的，插件每次按键只能读 4 万行。**连打十几个字**后整张表就在内存里了，
之后应该稳定命中。如果一直很少：

- 确认 `cache.txt` 不是被截断了一半（行数应为 9 万以上）；
- 设置 `RIME_EN_GLOSS_DEBUG=1`，看日志里 `with_comment failed` 是否在刷屏。

---

## 打字卡顿 / 宿主程序整个卡死

插件在宿主的输入线程里运行，任何耗时操作都会让它冻结。请确认：

- lua 里没有 `os.execute` / `io.popen` / `require("simplehttp")`；
- `MAX_LINES_PER_CALL` 没有被改得过大（默认 40000 ≈ 0.1 秒）；
- `PROCESS_LIMIT` 保持 30（遍历几百个候选会让拼音输入卡死）；
- 没有在 filter 里 `require` 大文件（几 MB 的 Lua 字典会冻结 1–2 秒）。

排查手段：打开 `RIME_EN_GLOSS_DEBUG=1`，按几个键，看 `filter_debug.log` 是否有输出；
删掉日志后重新打字，如果文件立刻变大说明确实在执行慢路径。

---

## 打不出汉字了

八成是挂上了 `lua_processor`，或者 lua 有语法错误导致整条按键处理链中断。

- 只保留 `lua_filter@*input_text*filter`，不要加 processor；
- 用真实 Lua 运行时校验语法（注意 `cand.end` 里的 `end` 是保留字，必须写成 `cand["end"]`）：

```bash
pip install lupa
python -c "import lupa,io; lua=lupa.LuaRuntime(); f=lua.eval('function(s) local fn,e=load(s); if fn then return \"OK\" else return e end end'); print(f(io.open('lua/input_text.lua',encoding='utf-8').read()))"
```

应急办法：先把方案里的 filter 行注释掉，重新部署，打字立刻恢复。

---

## 英文位置不对 / 想换成别的格式

格式在 `lua/input_text.lua` 的 `with_comment()` 里：

```lua
merged = orig .. ", " .. extra     -- 编码, 英文
```

想只显示英文（`1. 告诉   to tell; to inform`）就把 `orig` 那两行去掉。

---

## 想改某个词的译文

```python
# tools/glossary.py
SINGLE = {"打": "to hit; to play", ...}    # 单字
WORD   = {"东西": "thing; stuff", ...}     # 词组
```

改完 `python tools/build_cache.py`，重启 `WeaselServer.exe`（或直接打字，插件会重新读表）。
`SINGLE` / `WORD` 优先级最高，一定覆盖词典结果。

---

## Linux / macOS

- 前端要带 librime-lua（ibus-rime / fcitx5-rime 的发行版包通常都带；否则自行编译 `librime-lua`）。
- 用户目录：Linux `~/.config/ibus/rime`（fcitx5 为 `~/.local/share/fcitx5/rime`），macOS `~/Library/Rime`。
- 重新部署：Linux `ibus-daemon -drx` 或 fcitx5 的「重新部署」；macOS 鼠须管菜单里的「重新部署」。
- `build_cache.py --dict-dir <用户目录>` 才能读到词频权重。

## 打人名（如 杨满钊）第一次出来的不是这个名字

这是词库权重问题，不是 bug：人名用的字往往与常用字同码
（例：wubi86 里 `qjh` 同时对应 刈(600万) 和 钊(351万)，刈 更常用所以排前面）。
第一次打出错误候选后**选一次正确的字**，用户词库会记住，之后就对了。

想让某个高频人名**第一次就对**，建一个扩展词库（不动基础词表）：

```yaml
# wubi86.extended.dict.yaml
---
name: wubi86.extended
version: "0.1"
sort: by_weight
import_tables:
  - wubi86
...
杨满钊	sniagwqjh	50000000   # 实际敲的整串编码
杨满钊	siqj	50000000           # 标准三字词编码 AaBaCaCb
```

再在方案补丁里把词典指过去（`<schema>.custom.yaml`）：

```yaml
patch:
  translator/dictionary: wubi86.extended
```

重新部署后，整串编码会直接出整个人名。
