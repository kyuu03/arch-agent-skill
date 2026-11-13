# 数据格式与来源边界

## 项目记录

总账沿用技能 `references/requirements.md` 及 `scripts/check_requirements.py` 的约定。页面主要读取：

- `version/parentVersion/designRevision`：需求基线与成果身份分别保存。
- `requirements[]`：`id,parent,title,statement,acceptance[],sources[],lifecycle`。
- `tasks[]`：`id,requirementIds[],status,scope,purpose,limitations`。
- `reviews[]`：`id,requirementIds[],kind,verdict,scope,evidence[],appliesToVersion`及适用成果散列。
- `changes/pendingImpacts`：变化与待核影响。

页面读取并不代替结构检查。当前页面不自动计算父项验收闸门，不把子任务done汇总成要求passed。

## 资料包 v1

容器是UTF-8 JSON，建议扩展名 `.acpack.json`。不是ZIP，不接收可执行安装器或二进制附件。

```json
{
  "schema": "ac-library-pack/v1",
  "id": "climate-methods",
  "version": "1.0.0",
  "title": "微气候方法",
  "author": "整理者",
  "license": "private-use-only",
  "entries": [
    {
      "id": "shade-example",
      "kind": "knowledge",
      "title": "树荫研究记录",
      "content": "这里是带条件、未验证的文字示例，不是规范结论。",
      "sources": [{"title":"资料题名","locator":"页码或章节","reading_scope":"实际核读范围"}],
      "verification": "unverified",
      "sharing": "private",
      "verified_at": null,
      "review_trigger": "来源、气候条件或任务范围变化"
    }
  ],
  "sha256": "由seal函数计算，不要照抄此占位字符串"
}
```

上面的代码块解释字段，不是可安装样包。可安装样包在 `examples/`。

必填包字段：`schema,id,version,title,author,license,entries,sha256`。ID与version允许ASCII字母、数字、点、下划线、连字符，首位字母或数字，最长80字符。version当前不解析SemVer，不比较大小，不自动激活最新版。

必填条目字段：`id,kind,title,content,sources,verification,sharing`。

`kind`：`knowledge / experience / expert`。

`verification`：`unverified / case-supported / cross-context-supported / revised / invalid`。这是声明的证据状态，平台不会凭标签认定事实；导入不提升等级。

`sharing`：`private / shareable`。可分享也不表示任何使用方式都获许可，仍需看来源与license。

推荐扩展：`read_scope,verified_at,review_trigger,review_due,context,expectation,method,feedback,cost,counterexamples,decision_trace,limitations,related_requirement_ids`。导入和导出保留扩展字段；扩展不是指令，也不执行。sources应保留原定位信息，不将只有书目的一条记为已读正文。

`provenance` 为来源包身份对象数组：`id,version,author,license,sha256`。每次跨包选择导出追加直接来源，原许可与来源不被新包作者替换。包内生成新条目ID，但原包及散列保留在链中。

## 散列

计算前移除顶层 `sha256` 字段，按Python `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')` 规范化，再做SHA256十六进制小写。使用 `ac_platform.library.seal(pack)`；校验用 `validate(pack)`。

SHA256用于发现意外或人为变动，不是签名。任何人都可对伪造内容重新计算合法散列；作者、真实性、许可与专业结论仍须判断。

## 容量与当前限制

- 单包8MiB、1–100条；正文每条128KiB。
- 无附件、无压缩解包、无执行钩子。
- sources及扩展字段原样保留，不自动验证URL可访问或页码正确。
- 同ID同版本不同散列不覆盖。
- 只读挂载来源不可在页面修改；新安装包放到自身数据目录。
- 来自多个目录的相同内容可能重复显示；当前不做语义去重或证据独立性判断。
