"""命令行入口。

命令（文档15 §7.16）：
python -m ridepulse.cli validate --input data/verified/feedback_verified.csv
python -m ridepulse.cli collect --connector app_store_rss --app-id 1555629744 --storefront us --limit 50
python -m ridepulse.cli run --input data/verified/feedback_verified.csv
python -m ridepulse.cli resume --run-id RUN-20260801-120000
python -m ridepulse.cli evaluate --gold data/verified/annotation_gold.csv
python -m ridepulse.cli push-feishu --run-id RUN-20260801-120000
每条命令必须提供 --help。
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="ridepulse", description="RidePulse AI CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="校验CSV数据")
    sub.add_parser("collect", help="从公开连接器采集")
    sub.add_parser("run", help="运行完整流水线")
    sub.add_parser("resume", help="从失败步骤恢复")
    sub.add_parser("evaluate", help="模型评测")
    sub.add_parser("push-feishu", help="推送飞书")

    args = parser.parse_args()
    raise NotImplementedError(f"命令 {args.command} 待实现（8月9日）")


if __name__ == "__main__":
    main()
