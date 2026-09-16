# -*- coding: utf-8 -*-
"""入口：双击运行，无控制台窗口。"""
import sys

# 让脚本所在目录的 keymon 包优先于其它同名包
if sys.path[0].endswith("key-usage-widget"):
    sys.path.insert(0, sys.path[0])

from keymon.ui import main

if __name__ == "__main__":
    main()
