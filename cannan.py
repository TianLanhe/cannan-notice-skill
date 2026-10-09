#!/usr/bin/env python3
"""Run with Python 3.10+, preferably .venv/bin/python."""
import sys

if sys.version_info < (3, 10):
    print('需要 Python 3.10+。请使用 .venv/bin/python，或 Python 3.10+ 创建虚拟环境。', file=sys.stderr)
    raise SystemExit(2)

from cannan_cli.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
