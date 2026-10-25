"""命令行入口。

命令：
python -m ridepulse.cli validate --input data/verified/feedback_verified.csv
python -m ridepulse.cli collect --connector app_store_rss --app-id 1555629744 --storefront us --limit 50
python -m ridepulse.cli run --input data/verified/feedback_verified.csv [--offline] [--run-id RUN-...]
python -m ridepulse.cli resume --run-id RUN-20260801-120000
python -m ridepulse.cli evaluate --run-id RUN-... --gold data/verified/annotation_gold.csv
python -m ridepulse.cli push-feishu --run-id RUN-... [--card-id EC-2026-0001]
每条命令必须提供 --help。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ridepulse.config import get_config
from ridepulse.database import Database
from ridepulse.ingest import load_csv


def _load_dotenv(path: str | None = None) -> None:
    """加载项目根目录 .env（纯标准库，不覆盖已存在的环境变量）。

    .env 已在 .gitignore 中，凭证绝不入库。
    """
    target = Path(path) if path else (Path(__file__).resolve().parent.parent.parent / ".env")
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _cmd_validate(args: argparse.Namespace) -> int:
    """校验 CSV 并打印报告。"""
    report = load_csv(args.input, out_dir=str(Path(args.input).parent / "import_check"))
    print(f"total_rows={report.total_rows} valid_rows={report.valid_rows} "
          f"invalid_rows={report.invalid_rows} unverified={report.unverified_evidence_count}")
    for warning in report.warnings[:50]:
        print(f"  [警告] {warning}")
    if report.duplicate_ids:
        print(f"  重复 ID: {report.duplicate_ids}")
    if report.invalid_rows:
        return 2
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    """从合规公开连接器采集。"""
    if args.connector != "app_store_rss":
        print(f"未知连接器: {args.connector}（当前支持 app_store_rss）", file=sys.stderr)
        return 2
    from ridepulse.collectors.app_store_rss import AppStoreRSSConnector
    connector = AppStoreRSSConnector(app_id=args.app_id, storefront=args.storefront)
    reviews = connector.fetch(limit=args.limit, out_dir=args.out_dir)
    print(f"采集完成: {len(reviews)} 条评论，原始响应保存在 {args.out_dir or 'output/collects/'}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """运行完整流水线。"""
    from ridepulse.pipeline import Pipeline
    config = get_config()
    db = Database(config.db_path)
    pipeline = Pipeline(run_id=args.run_id, db=db, config=config, offline_mode=args.offline)
    summary = pipeline.run(args.input)
    print(json.dumps(summary.model_dump(), ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    """从失败步骤恢复。"""
    from ridepulse.pipeline import Pipeline
    config = get_config()
    db = Database(config.db_path)
    pipeline = Pipeline(run_id=args.run_id, db=db, config=config)
    summary = pipeline.resume()
    print(f"resume 完成: {summary.state.value}")
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    """模型评测：run 输出 vs gold 标注。"""
    import csv as _csv

    from ridepulse.evaluation import evaluate_model
    config = get_config()
    db = Database(config.db_path)
    classifications = db.conn.execute(
        "SELECT * FROM classifications WHERE run_id=? ORDER BY feedback_id", (args.run_id,)
    ).fetchall()
    if not classifications:
        print(f"run {args.run_id} 没有分类结果", file=sys.stderr)
        return 2

    gold_rows: list[dict] = []
    with Path(args.gold).open("r", encoding="utf-8-sig", newline="") as f:
        for row in _csv.DictReader(f):
            gold_rows.append(row)

    # 构造 ClassificationResult 列表（复用 pipeline 的加载逻辑）
    from ridepulse.pipeline import Pipeline
    model_outputs = Pipeline(run_id=args.run_id, db=db, config=config)._load_classifications()
    metrics = evaluate_model(model_outputs, gold_rows)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    out_path = Path(config.output_dir) / args.run_id / "metrics.json"
    out_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out_path}")
    return 0


def _cmd_push_feishu(args: argparse.Namespace) -> int:
    """推送证据卡到飞书（最小真实闭环）。"""
    import os

    from ridepulse.delivery import push_card
    from ridepulse.feishu_client import FeishuClient

    config = get_config()
    if not config.feishu_configured:
        print("未配置飞书（需要 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BITABLE_APP_TOKEN）",
              file=sys.stderr)
        return 2

    db = Database(config.db_path)
    cards = db.list_evidence_cards(args.run_id)
    if args.card_id:
        cards = [card for card in cards if card["card_id"] == args.card_id]
    if not cards:
        print(f"run {args.run_id} 没有证据卡（card_id={args.card_id}）", file=sys.stderr)
        return 2

    client = FeishuClient(
        app_id=config.feishu_app_id,
        app_secret=config.feishu_app_secret,
        bitable_app_token=config.feishu_bitable_app_token,
        tables={
            "feedback": config.feishu_feedback_table_id or "",
            "evidence": config.feishu_evidence_table_id or "",
            "review": config.feishu_review_table_id or "",
            "experiment": config.feishu_experiment_table_id or "",
        },
    )
    for card in cards:
        remote_id = push_card(client, dict(card), args.run_id)
        db.insert_delivery(args.run_id, object_type="evidence_card",
                           object_id=card["card_id"], status="delivered")
        db.audit(args.run_id, actor="cli", action="push_feishu",
                 object_type="evidence_card", object_id=card["card_id"],
                 after={"remote_record_id": remote_id})
        print(f"已推送 {card['card_id']} -> {remote_id}")
    return 0


def _cmd_check_llm(args: argparse.Namespace) -> int:
    """检查 LLM 接入：打印三层模型分工，--live 时真发一次请求验证端点。"""
    from ridepulse.llm_client import LLMClientError, probe_endpoint, resolve_reasoning_effort

    config = get_config()
    roles = {"classify": "分类", "review": "复判", "evidence": "证据卡"}
    print(f"provider  : {config.llm_provider}")
    print(f"base_url  : {config.llm_base_url}")
    print(f"api_key   : {'已配置' if config.llm_api_key else '未配置'}")
    for key, model in config.llm_model_stack.items():
        effort = resolve_reasoning_effort(model, config.reasoning_effort_for(key))
        suffix = f"（reasoning_effort={effort}）" if effort else ""
        print(f"{roles.get(key, key):<9} : {model}{suffix}")
    if not args.live:
        print("\n加 --live 会真发一次最小请求，核对端点、模型 ID 与回包模型名。")
        return 0
    if not config.llm_configured:
        print("未配置 API key，无法发起真实调用（OPENAI_API_KEY 或 LLM_API_KEY）",
              file=sys.stderr)
        return 2
    try:
        result = probe_endpoint(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            models=config.llm_model_stack,
            reasoning_effort=config.reasoning_effort_for("classify"),
        )
    except LLMClientError as exc:
        print(f"自检失败: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("missing_from_list"):
        print(f"提示: 以下模型不在 /models 清单中 {result['missing_from_list']}，"
              "清单可能不全，以真实调用是否成功为准。", file=sys.stderr)
    return 0


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(prog="ridepulse", description="RidePulse AI CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="校验CSV数据")
    p_validate.add_argument("--input", required=True, help="CSV 文件路径")

    p_collect = sub.add_parser("collect", help="从公开连接器采集")
    p_collect.add_argument("--connector", default="app_store_rss", help="连接器名")
    p_collect.add_argument("--app-id", required=True, help="App Store App ID")
    p_collect.add_argument("--storefront", default="us", help="地区（us/cn 等）")
    p_collect.add_argument("--limit", type=int, default=50, help="最多采集条数")
    p_collect.add_argument("--out-dir", default=None, help="原始响应保存目录")

    p_run = sub.add_parser("run", help="运行完整流水线")
    p_run.add_argument("--input", required=True, help="CSV 文件路径")
    p_run.add_argument("--offline", action="store_true",
                       help="离线基线：使用数据标注列代替 LLM 分类（开发/演示）")
    p_run.add_argument("--run-id", default=None, help="指定 run_id（默认自动生成）")

    p_resume = sub.add_parser("resume", help="从失败步骤恢复")
    p_resume.add_argument("--run-id", required=True, help="要恢复的 run_id")

    p_eval = sub.add_parser("evaluate", help="模型评测")
    p_eval.add_argument("--run-id", required=True, help="模型输出所在 run_id")
    p_eval.add_argument("--gold", required=True, help="gold 标注 CSV 路径")

    p_push = sub.add_parser("push-feishu", help="推送飞书")
    p_push.add_argument("--run-id", required=True, help="证据卡所在 run_id")
    p_push.add_argument("--card-id", default=None, help="只推送指定 card_id")

    p_check = sub.add_parser("check-llm", help="检查 LLM 接入（模型分工 / 端点连通性）")
    p_check.add_argument("--live", action="store_true",
                         help="真发一次最小请求，核对端点与回包模型名")

    args = parser.parse_args()
    handlers = {
        "validate": _cmd_validate,
        "collect": _cmd_collect,
        "run": _cmd_run,
        "resume": _cmd_resume,
        "evaluate": _cmd_evaluate,
        "push-feishu": _cmd_push_feishu,
        "check-llm": _cmd_check_llm,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
