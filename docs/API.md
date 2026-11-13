# 本机接口

默认端口8850；Host必须是实际监听的`127.0.0.1:端口`。不提供CORS。设计文件与总账没有写入API。

| 方法 / 路径 | 作用 |
| --- | --- |
| GET / | 平台页面 |
| GET /api/state | 当前项目记录、库条目与配置白名单成果 |
| GET /api/session | 本次进程的管理令牌；本机页面使用 |
| GET /health | 本体名称与版本 |
| GET /file?path=... | 仅下载配置白名单文件，不浏览任意目录 |
| POST /api/packs/preview | `{pack}`：校验格式和散列，返回条目与提醒 |
| POST /api/packs/install | `{pack,confirmedSha256}`：安装相同确认散列的包 |
| POST /api/packs/export | `{keys,metadata,allowPrivate}`：选择导出并返回包及预览，不写入原库 |

POST需要：同源`Origin: http://127.0.0.1:实际端口`、`X-AC-Token`来自session、JSON请求体。令牌随进程重启变化，不能把session响应写入共享库。绑定与已有笔记属于受信任本机配置；不以此机制防范已控制本机进程或恶意浏览器扩展。

安装确认是页面先预览再显式发送散列；API也核验散列一致，但不会替人证明已经阅读内容。包校验不证明来源可信。

`keys` 是当前目录条目的不透明键，由state返回的包key与条目id组成；不是任意文件路径。metadata包含`id,version,title,author,license`。allowPrivate必须显式为true才允许选定私人条目导出，默认false。

响应：400格式或绑定错误，403非本地/越界/令牌无效，404无此页面，405不允许写入，409同包同版本内容冲突，413请求过大。此版不提供授权给公网客户端的机制。
