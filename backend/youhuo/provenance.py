"""被验证过的那棵源码树的指纹。

**读一份报告，不等于跑过一次验证。**

重型验证——一百万条 v5 可信内核断言、400 个 Saga 故障与补偿场景、5,000 请求 100 并发
的真实回环——单次要跑好几分钟，所以它们的结论以 JSON 留在 `reports/` 里，由
`check_artifacts_v6.py` 读取，`verify_all` 再据此报告"全部阶段通过"。

于是出现过这样一段时间：`reports/mass_audit_v5_1000000.json` 是 08-08 生成的，而
`v5_services.py`（含 `PurposeBoundPolicy.authorize` 的字段规范化）和 `security.py`
在 08-10 被改过。那两天里 `verify_all` 每次都说通过，读的却是改动之前的结论。这与
"页面登记在 JSON 里就算够得着""`node --check` 过了就算能跑"是同一类错误：**断言的是
一条记录，而不是当前的事实。**

所以每份重型报告都记下它当时验证的那棵树的指纹，检查器重新算一遍并比对。对不上就是
过期，必须重跑 `verify_heavy`——而不是继续引用一个旧结论。

指纹只覆盖 `backend/youhuo/*.py`：那是这些验证真正在考的东西。改脚本、改文档、改前端
不会让一百万条后端断言失效，把它们也算进去只会制造无谓的重跑。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent


def source_digest() -> str:
    """`backend/youhuo/*.py` 的稳定散列。

    行尾统一成 LF 再算：这个仓库在 Windows 上检出为 CRLF、在 Linux 上是 LF，
    不归一化的话同一份代码在两台机器上会得到两个指纹，报告就会永远显示过期。
    """
    digest = hashlib.sha256()
    for path in sorted(SOURCE_ROOT.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()
