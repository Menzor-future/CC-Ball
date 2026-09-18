# -*- coding: utf-8 -*-
"""入口：双击运行，无控制台窗口。"""
import sys
import os

# 让脚本所在目录的 keymon 包优先于其它同名包
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# 日志目录跟随平台惯例（mac 无 LOCALAPPDATA 环境变量）
from keymon.config import USER_CONFIG_PATH

_BOOT_LOG = os.path.join(os.path.dirname(USER_CONFIG_PATH), "boot.log")

def _boot(msg):
    try:
        os.makedirs(os.path.dirname(_BOOT_LOG), exist_ok=True)
        with open(_BOOT_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

_boot(f"=== app.pyw boot ===")
_boot(f"exe={sys.executable} ver={sys.version}")
_boot(f"cwd={os.getcwd()}")
_boot(f"stderr={getattr(sys, 'stderr', None)} stdout={getattr(sys, 'stdout', None)}")

# pythonw 下 stdout/stderr 可能为 None 或无效句柄，Qt 写调试输出会 crash。
# 统一重定向到 devnull，保证双击（start 启动）和命令行启动行为一致。
for _stream in ("stdout", "stderr"):
    _f = getattr(sys, _stream, None)
    try:
        _bad = _f is None or _f.closed or not _f.writable()
    except Exception:
        _bad = True
    if _bad:
        setattr(sys, _stream, open(os.devnull, "w", encoding="utf-8"))
_boot("stderr redirected")

try:
    from keymon.ui_qt import main
    _boot("import ok")
except Exception:
    import traceback
    _boot("IMPORT FAILED:\n" + traceback.format_exc())
    raise

if __name__ == "__main__":
    main()
