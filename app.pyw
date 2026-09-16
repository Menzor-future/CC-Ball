# -*- coding: utf-8 -*-
"""入口：双击运行，无控制台窗口。"""
import sys
import os

# 让脚本所在目录的 keymon 包优先于其它同名包
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from keymon.ui_qt import main

if __name__ == "__main__":
    main()
