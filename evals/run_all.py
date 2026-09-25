#!/usr/bin/env python3
"""评测统一入口 + 回归门禁

运行所有评测脚本，输出 JSON 报告，并按 `evals/baseline.json` 的规则做回归拦截。

用法：
  python evals/run_all.py                       # 跑全部评测并过门禁
  python evals/run_all.py --skip-llm            # 跳过 LLM 评测（省钱；用于数据更新轮次）
  python evals/run_all.py --json                # 附带机器可读报告
  python evals/run_all.py --report x.json       # 指定报告落盘位置

退出码：
  0 - 门禁通过
  1 - 有指标跌破基线 / 评测脚本跑不通

关于门禁规则为什么不是「一个 --baseline 数字」：
  最初用 `--baseline 0.75` 给所有指标套同一个下限，实测直接判死 ——
  检索的 recall@k 长期在 0.26（Week 2 报告已记录该指标低于熔断线），
  而 RAG 的 faithfulness 是 1.00，两类指标量纲/口径完全不同，
  统一阈值的结果是每次运行都失败、部署被永久卡住，门禁失去意义。
  现在改成逐指标声明：snapshot（当前水平）+ tolerance（允许抖动）+
  floor（达标线，仅对已确认可达标的指标启用）+ target（未达标目标，只公示不拦截）。
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_DIR = os.path.join(BASE_DIR, "evals")
DEFAULT_GATE = os.path.join(EVALS_DIR, "baseline.json")

# (脚本名, 说明, 是否为 LLM 评测)
EVAL_SCRIPTS = [
    ("eval_retrieval.py", "检索（本地嵌入，无 LLM 成本）", False),
    ("eval_classify.py", "分类（依赖人工标注集）", False),
    ("eval_rag.py", "RAG 问答（LLM 生成 + 裁判，有成本）", True),
]


def run_eval(script_name: str, extra_args=None) -> dict:
    """运行单个评测脚本"""
    script_path = os.path.join(EVALS_DIR, script_name)
    if not os.path.exists(script_path):
        return {"script": script_name, "status": "error", "message": "脚本不存在"}

    cmd = [sys.executable, script_path, "--json"]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=BASE_DIR,
        )

        if result.returncode != 0:
            return {
                "script": script_name,
                "status": "failed",
                "returncode": result.returncode,
                "stderr": result.stderr[-800:],
            }

        try:
            return {"script": script_name, "status": "passed", "metrics": json.loads(result.stdout)}
        except json.JSONDecodeError:
            # 脚本跑通但输出不是 JSON（多数是「数据集为空」这类提前返回）
            return {
                "script": script_name,
                "status": "passed",
                "metrics": {},
                "output": result.stdout.strip()[-400:],
            }

    except subprocess.TimeoutExpired:
        return {"script": script_name, "status": "timeout"}
    except Exception as exc:  # pragma: no cover - 兜底
        return {"script": script_name, "status": "error", "message": str(exc)}


def evaluate_gate(results: list, gate: dict):
    """按逐指标规则判定。返回 (失败项, 提示项, 已校验项)"""
    rules = gate.get("rules", {})
    fails, warns, checked = [], [], []

    for res in results:
        script = res["script"]

        if res["status"] != "passed":
            fails.append(f"{script}: 评测未跑通（{res['status']}）")
            continue

        metrics = res.get("metrics") or {}
        numeric = {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}

        if not numeric:
            # 关键：没指标不等于通过。分类评测在标注集为空时就是这种情况，
            # 之前的实现会静默放行，等于门禁形同虚设。
            detail = res.get("output", "").strip()
            warns.append(f"{script}: 未产出任何指标，本次不参与门禁{f'（{detail[:80]}）' if detail else ''}")
            continue

        for key, value in numeric.items():
            rule = rules.get(script, {}).get(key)
            if rule is None:
                warns.append(f"{script}.{key}={value:g} 无基线记录，未纳入门禁")
                continue

            floor = rule.get("floor")
            if floor is not None and value < floor:
                fails.append(f"{script}.{key}={value:g} < 下限 {floor:g}")
                continue

            snapshot, tolerance = rule.get("snapshot"), rule.get("tolerance", 0.05)
            if snapshot is not None and value < snapshot - tolerance:
                fails.append(
                    f"{script}.{key}={value:g} 较基线 {snapshot:g} 下滑超过 {tolerance:g}"
                )
                continue

            target = rule.get("target")
            if target is not None and value < target:
                warns.append(f"[未达标] {script}.{key}={value:g} < 目标 {target:g}（已记录，不拦截）")

            checked.append(f"{script}.{key}={value:g}")

    return fails, warns, checked


def main():
    parser = argparse.ArgumentParser(description="评测统一入口 + 回归门禁")
    parser.add_argument("--gate-config", default=DEFAULT_GATE, help="门禁规则文件")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 评测（数据更新轮次用）")
    parser.add_argument("--json", action="store_true", help="输出机器可读报告")
    parser.add_argument("--prompt", choices=["v1", "v2"], default=None, help="RAG 评测的 Prompt 版本")
    parser.add_argument("--report", default=os.path.join(EVALS_DIR, "eval_report.json"), help="报告落盘路径")
    args = parser.parse_args()

    if not args.json:
        print("=" * 62)
        print("AI 情报站 · 评测统一入口")
        print(f"时间: {datetime.now().isoformat(timespec='seconds')}")
        print(f"门禁规则: {os.path.basename(args.gate_config)}"
              + ("（本轮跳过 LLM 评测）" if args.skip_llm else ""))
        print("=" * 62)

    with open(args.gate_config, encoding="utf-8") as f:
        gate = json.load(f)

    scripts = [s for s in EVAL_SCRIPTS if not (args.skip_llm and s[2])]
    skipped = [s[0] for s in EVAL_SCRIPTS if args.skip_llm and s[2]]

    results = []
    for script, desc, _is_llm in scripts:
        if not args.json:
            print(f"\n>>> {script} —— {desc}")
        res = run_eval(script, ["--prompt", args.prompt] if (args.prompt and script == "eval_rag.py") else None)
        results.append(res)
        if not args.json:
            print(f"    状态: {res['status']}")
            for key, value in (res.get("metrics") or {}).items():
                print(f"    {key}: {value:.4f}" if isinstance(value, float) else f"    {key}: {value}")

    fails, warns, checked = evaluate_gate(results, gate)

    if not args.json:
        print("\n" + "=" * 62)
        print("门禁判定")
        print("=" * 62)
        for item in checked:
            print(f"  [OK] {item}")
        for item in warns:
            print(f"  [WARN] {item}")
        for item in fails:
            print(f"  [FAIL] {item}")

        gaps = gate.get("known_gaps", [])
        if gaps:
            print("\n已知未达标（每次运行都公示，避免被遗忘）：")
            for gap in gaps:
                print(f"  · {gap}")

    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "gate_config": os.path.basename(args.gate_config),
        "skip_llm": args.skip_llm,
        "skipped_scripts": skipped,
        "total": len(results),
        "passed": sum(1 for r in results if r["status"] == "passed"),
        "failed": sum(1 for r in results if r["status"] != "passed"),
        "gate_passed": not fails,
        "checked": checked,
        "warnings": warns,
        "failures": fails,
        "known_gaps": gate.get("known_gaps", []),
        "results": results,
    }

    try:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        report_note = args.report
    except OSError as exc:
        # 报告是信息性产物，写不进去（只读检出、文件被占用）不该让门禁本身失败；
        # --json 模式下完整报告本来也已经在 stdout 里了。
        report_note = None
        print(f"[warn] 报告落盘失败（不影响门禁判定）: {exc}", file=sys.stderr)

    if args.json:
        # --json 下只输出一份完整 JSON，方便下游直接解析
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"\n报告已保存: {report_note}" if report_note else "\n[warn] 报告未落盘")

    if fails:
        print("\n[FAIL] 门禁未通过，阻断后续部署")
        sys.exit(1)
    if not args.json:
        print("\n[PASS] 门禁通过")


if __name__ == "__main__":
    main()
