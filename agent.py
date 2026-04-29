#!/usr/bin/env python3
"""
Doc/Knowledge Base Agent
------------------------
Automatically syncs code changes into:
1) technical change document
2) API change notes
3) FAQ
4) searchable knowledge base index

Usage:
  python agent.py --app all --base main --head HEAD
  python agent.py --app docs --base HEAD~1 --head HEAD --repo .
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class ChangedFile:
    status: str
    path: str


@dataclass
class APIChange:
    file: str
    change_type: str
    signature: str
    raw_line: str


@dataclass
class FAQItem:
    question: str
    answer: str
    source_hint: str


def run_git(args: List[str], repo: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(message)
    return result.stdout


def ensure_git_repo(repo: Path) -> None:
    try:
        _ = run_git(["rev-parse", "--is-inside-work-tree"], repo).strip()
    except RuntimeError as exc:
        raise RuntimeError(f"{repo} is not a git repository: {exc}") from exc


def get_changed_files(repo: Path, base: str, head: str) -> List[ChangedFile]:
    # name-status format examples:
    # M\tapp/service.py
    # A\tdocs/new.md
    output = run_git(["diff", "--name-status", f"{base}...{head}"], repo)
    changed: List[ChangedFile] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, path = parts
        changed.append(ChangedFile(status=status.strip(), path=path.strip()))
    return changed


def get_file_diff(repo: Path, base: str, head: str, path: str) -> str:
    return run_git(["diff", "-U0", f"{base}...{head}", "--", path], repo)


def classify_file(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs")):
        return "code"
    if lower.endswith((".md", ".rst", ".txt")):
        return "docs"
    if "test" in lower or lower.endswith(("_test.py", ".spec.ts", ".test.ts")):
        return "test"
    if lower.endswith((".json", ".yml", ".yaml", ".toml", ".ini")):
        return "config"
    return "other"


def detect_api_changes(path: str, diff_text: str) -> List[APIChange]:
    # Keep patterns simple and language-agnostic.
    add_patterns = [
        r"^\+\s*def\s+\w+\s*\(",
        r"^\+\s*class\s+\w+\s*[\(:]?",
        r"^\+\s*function\s+\w+\s*\(",
        r"^\+\s*export\s+function\s+\w+\s*\(",
        r"^\+\s*export\s+class\s+\w+",
        r"^\+\s*router\.(get|post|put|delete|patch)\(",
        r"^\+\s*app\.(get|post|put|delete|patch)\(",
    ]
    del_patterns = [p.replace(r"^\+", r"^-") for p in add_patterns]

    compiled_add = [re.compile(p) for p in add_patterns]
    compiled_del = [re.compile(p) for p in del_patterns]

    items: List[APIChange] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue

        if any(p.search(line) for p in compiled_add):
            items.append(
                APIChange(
                    file=path,
                    change_type="added_or_updated",
                    signature=extract_signature(line[1:].strip()),
                    raw_line=line,
                )
            )
        elif any(p.search(line) for p in compiled_del):
            items.append(
                APIChange(
                    file=path,
                    change_type="removed_or_replaced",
                    signature=extract_signature(line[1:].strip()),
                    raw_line=line,
                )
            )
    return items


def extract_signature(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) > 180:
        return line[:177] + "..."
    return line


def build_faq(changed_files: List[ChangedFile], api_changes: List[APIChange]) -> List[FAQItem]:
    faq: List[FAQItem] = []

    paths = [f.path.lower() for f in changed_files]
    statuses = [f.status for f in changed_files]

    if any("readme" in p or p.endswith(".md") for p in paths):
        faq.append(
            FAQItem(
                question="这次变更会影响现有文档吗？",
                answer="会。检测到文档文件改动，建议优先阅读技术变更说明和 API 变更说明。",
                source_hint="markdown files changed",
            )
        )

    if any(s == "A" for s in statuses):
        faq.append(
            FAQItem(
                question="是否新增了模块或能力？",
                answer="是。检测到新增文件，建议按新增目录补充架构图和模块说明。",
                source_hint="added files detected",
            )
        )

    if any("test" in p for p in paths):
        faq.append(
            FAQItem(
                question="测试策略有变化吗？",
                answer="有测试相关文件变更，建议检查覆盖率与关键回归用例是否更新。",
                source_hint="test files changed",
            )
        )

    if api_changes:
        faq.append(
            FAQItem(
                question="接口是否发生变化，是否需要通知上下游？",
                answer="是。检测到 API 签名变更，建议发布变更公告并更新调用示例。",
                source_hint="api signatures changed",
            )
        )

    # Always keep one generic newcomer-focused FAQ.
    faq.append(
        FAQItem(
            question="新人应该先看哪些内容？",
            answer="先阅读 technical_changes.md 的 Overview，再看 api_changes.md 的 Breaking/Non-breaking，最后看 FAQ。",
            source_hint="default onboarding guidance",
        )
    )

    return faq


def technical_summary(changed: List[ChangedFile], per_file_diffs: Dict[str, str]) -> str:
    total = len(changed)
    grouped: Dict[str, int] = {}
    for f in changed:
        grouped[classify_file(f.path)] = grouped.get(classify_file(f.path), 0) + 1

    top_files = changed[:12]
    bullets = []
    for f in top_files:
        diff = per_file_diffs.get(f.path, "")
        add_count = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
        del_count = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
        bullets.append(f"- `{f.path}` ({f.status}) +{add_count}/-{del_count}")

    detail = "\n".join(bullets) if bullets else "- 无文件变更"
    grouped_text = ", ".join(f"{k}: {v}" for k, v in sorted(grouped.items())) or "none"

    return (
        f"## Overview\n"
        f"- 变更文件总数: **{total}**\n"
        f"- 文件类型分布: {grouped_text}\n"
        f"- 生成时间: {dt.datetime.now().isoformat(timespec='seconds')}\n\n"
        f"## File-level Changes\n"
        f"{detail}\n"
    )


def api_changes_markdown(api_changes: List[APIChange]) -> str:
    if not api_changes:
        return (
            "## API Change Detection\n"
            "- 未检测到明显 API 签名变更。\n\n"
            "## Notes\n"
            "- 本检测基于 diff 规则匹配，建议人工复核关键模块。\n"
        )

    breaking = [x for x in api_changes if x.change_type == "removed_or_replaced"]
    non_breaking = [x for x in api_changes if x.change_type == "added_or_updated"]

    def section(title: str, items: List[APIChange]) -> str:
        if not items:
            return f"### {title}\n- 无\n"
        lines = [f"### {title}"]
        for it in items:
            lines.append(f"- `{it.file}` -> `{it.signature}`")
        return "\n".join(lines) + "\n"

    return (
        "## API Change Detection\n"
        "- 该报告从代码 diff 中自动提取函数/类/路由等签名变更。\n\n"
        + section("Potential Breaking Changes", breaking)
        + "\n"
        + section("Potential Non-breaking Changes", non_breaking)
    )


def faq_markdown(items: List[FAQItem]) -> str:
    lines = ["## FAQ"]
    for i, item in enumerate(items, start=1):
        lines.append(f"### Q{i}. {item.question}")
        lines.append(item.answer)
        lines.append(f"_source: {item.source_hint}_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def pr_review_markdown(changed: List[ChangedFile], api_changes: List[APIChange]) -> str:
    risks: List[str] = []
    suggestions: List[str] = []

    paths = [f.path.lower() for f in changed]
    if any("config" in p or p.endswith((".yml", ".yaml", ".json", ".toml")) for p in paths):
        risks.append("检测到配置类改动，可能影响部署环境一致性。")
    if any("auth" in p or "permission" in p or "security" in p for p in paths):
        risks.append("检测到鉴权/安全相关改动，需重点检查权限边界与日志脱敏。")
    if len(changed) > 20:
        risks.append("本次改动文件较多，建议拆分评审并增加回归测试范围。")
    if api_changes:
        risks.append("检测到 API 签名变更，存在上下游兼容性风险。")
    if not risks:
        risks.append("未检测到明显高风险改动，建议按常规流程完成评审。")

    suggestions.extend(
        [
            "对关键路径新增或修改代码补齐单元测试。",
            "对潜在 breaking change 提供迁移说明和版本提示。",
            "上线前执行一次端到端冒烟验证。",
        ]
    )

    return (
        "## PR Review Report\n"
        "### Risks\n"
        + "\n".join(f"- {x}" for x in risks)
        + "\n\n### Suggestions\n"
        + "\n".join(f"- {x}" for x in suggestions)
        + "\n"
    )


def release_notes_markdown(changed: List[ChangedFile], api_changes: List[APIChange]) -> str:
    added = [f.path for f in changed if f.status == "A"]
    modified = [f.path for f in changed if f.status == "M"]
    removed = [f.path for f in changed if f.status.startswith("D")]
    api_count = len(api_changes)

    lines = [
        "## Release Notes",
        "### Highlights",
        f"- 本次涉及 {len(changed)} 个文件变更，新增 {len(added)}，修改 {len(modified)}，删除 {len(removed)}。",
        f"- 检测到 API 变更 {api_count} 处，发布前请确认兼容性。",
        "",
        "### Added",
    ]
    lines.extend([f"- `{p}`" for p in added] or ["- 无"])
    lines.append("")
    lines.append("### Changed")
    lines.extend([f"- `{p}`" for p in modified] or ["- 无"])
    lines.append("")
    lines.append("### Removed")
    lines.extend([f"- `{p}`" for p in removed] or ["- 无"])
    lines.append("")
    lines.append("### Upgrade Notes")
    lines.append("- 如存在接口签名变更，请先更新调用方 SDK/参数映射后再发布。")
    return "\n".join(lines) + "\n"


def onboarding_markdown(changed: List[ChangedFile]) -> str:
    top_paths = [f.path for f in changed[:10]]
    return (
        "## Onboarding Guide\n"
        "### First Read Path\n"
        "- 先阅读 `technical_changes.md` 了解改动范围。\n"
        "- 再阅读 `api_changes.md` 确认是否有 breaking change。\n"
        "- 最后阅读 `faq.md` 快速建立上下文。\n\n"
        "### Changed Modules To Learn\n"
        + ("\n".join(f"- `{p}`" for p in top_paths) if top_paths else "- 无")
        + "\n\n### Suggested Learning Plan\n"
        "- Day 1: 理解核心模块职责与目录结构。\n"
        "- Day 2: 跟踪一次完整调用链并本地调试。\n"
        "- Day 3: 完成一个小改动并提交 PR。\n"
    )


def qa_pairs(changed: List[ChangedFile], api_changes: List[APIChange], faq: List[FAQItem]) -> List[Dict[str, str]]:
    pairs: List[Dict[str, str]] = []
    pairs.append(
        {
            "question": "本次代码改动规模如何？",
            "answer": f"本次共变更 {len(changed)} 个文件，可在 technical_changes.md 查看详情。",
            "source": "technical_changes.md",
        }
    )
    pairs.append(
        {
            "question": "本次是否有接口变更？",
            "answer": f"检测到 {len(api_changes)} 处 API 变更，详见 api_changes.md。",
            "source": "api_changes.md",
        }
    )
    for item in faq[:5]:
        pairs.append(
            {
                "question": item.question,
                "answer": item.answer,
                "source": "faq.md",
            }
        )
    return pairs


def write_outputs(
    output_dir: Path,
    technical_md: str,
    api_md: str,
    faq_md: str,
    changed_files: List[ChangedFile],
    api_changes: List[APIChange],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "technical_changes.md").write_text(technical_md, encoding="utf-8")
    (output_dir / "api_changes.md").write_text(api_md, encoding="utf-8")
    (output_dir / "faq.md").write_text(faq_md, encoding="utf-8")

    kb = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "documents": [
            {"id": "technical_changes", "path": str(output_dir / "technical_changes.md"), "type": "technical"},
            {"id": "api_changes", "path": str(output_dir / "api_changes.md"), "type": "api"},
            {"id": "faq", "path": str(output_dir / "faq.md"), "type": "faq"},
        ],
        "changed_files": [asdict(x) for x in changed_files],
        "api_changes": [asdict(x) for x in api_changes],
    }
    (output_dir / "knowledge_base.json").write_text(
        json.dumps(kb, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_usage_log(
    log_file: Path,
    app: str,
    repo: Path,
    base: str,
    head: str,
    changed_files: List[ChangedFile],
    api_changes: List[APIChange],
    generated: List[Path],
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    by_status: Dict[str, int] = {}
    for item in changed_files:
        by_status[item.status] = by_status.get(item.status, 0) + 1

    payload = {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "app": app,
        "repo": str(repo),
        "base": base,
        "head": head,
        "changed_files_count": len(changed_files),
        "api_changes_count": len(api_changes),
        "changed_by_status": by_status,
        "artifacts_count": len(generated),
        "artifacts": [str(p) for p in generated],
    }
    with log_file.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-generate docs/knowledge-base from git changes."
    )
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--base", default="main", help="Base git ref (default: main)")
    parser.add_argument("--head", default="HEAD", help="Head git ref (default: HEAD)")
    parser.add_argument(
        "--output",
        default="docs/agent",
        help="Output directory (default: docs/agent)",
    )
    parser.add_argument(
        "--app",
        default="all",
        choices=["docs", "review", "release", "onboarding", "qa", "all"],
        help="Application to run (default: all)",
    )
    parser.add_argument(
        "--log-file",
        default="docs/agent/usage_metrics.jsonl",
        help="Usage metrics output file in JSONL format",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    output_dir = (repo / args.output).resolve()
    log_file = (repo / args.log_file).resolve()

    try:
        ensure_git_repo(repo)
        changed_files = get_changed_files(repo, args.base, args.head)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 2

    if not changed_files:
        generated = [
            output_dir / "technical_changes.md",
            output_dir / "api_changes.md",
            output_dir / "faq.md",
            output_dir / "knowledge_base.json",
            output_dir / "pr_review.md",
            output_dir / "release_notes.md",
            output_dir / "onboarding.md",
            output_dir / "qa_pairs.json",
        ]
        output_dir.mkdir(parents=True, exist_ok=True)
        write_markdown(output_dir / "technical_changes.md", "## Overview\n- 在指定范围内无代码变更。\n")
        write_markdown(output_dir / "api_changes.md", "## API Change Detection\n- 在指定范围内无 API 变更。\n")
        write_markdown(
            output_dir / "faq.md",
            "## FAQ\n### Q1. 这次为什么没有输出内容？\n因为 base...head 范围内没有检测到变更。\n",
        )
        (output_dir / "knowledge_base.json").write_text(
            json.dumps(
                {
                    "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "documents": [],
                    "changed_files": [],
                    "api_changes": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_markdown(output_dir / "pr_review.md", "## PR Review Report\n- 在指定范围内无改动。\n")
        write_markdown(output_dir / "release_notes.md", "## Release Notes\n- 在指定范围内无改动。\n")
        write_markdown(output_dir / "onboarding.md", "## Onboarding Guide\n- 在指定范围内无改动。\n")
        (output_dir / "qa_pairs.json").write_text(
            json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        append_usage_log(
            log_file=log_file,
            app=args.app,
            repo=repo,
            base=args.base,
            head=args.head,
            changed_files=[],
            api_changes=[],
            generated=generated,
        )
        print(f"[OK] No changes. Empty artifacts generated at: {output_dir}")
        print(f"[OK] Usage logged: {log_file}")
        return 0

    per_file_diffs: Dict[str, str] = {}
    all_api_changes: List[APIChange] = []

    for f in changed_files:
        try:
            diff = get_file_diff(repo, args.base, args.head, f.path)
            per_file_diffs[f.path] = diff
            all_api_changes.extend(detect_api_changes(f.path, diff))
        except Exception as exc:
            per_file_diffs[f.path] = f"[WARN] Failed to get diff: {exc}"

    run_docs = args.app in ("docs", "all")
    run_review = args.app in ("review", "all")
    run_release = args.app in ("release", "all")
    run_onboarding = args.app in ("onboarding", "all")
    run_qa = args.app in ("qa", "all")

    technical_md = technical_summary(changed_files, per_file_diffs)
    api_md = api_changes_markdown(all_api_changes)
    faq_items = build_faq(changed_files, all_api_changes)
    faq_md = faq_markdown(faq_items)
    generated: List[Path] = []

    if run_docs:
        write_outputs(output_dir, technical_md, api_md, faq_md, changed_files, all_api_changes)
        generated.extend(
            [
                output_dir / "technical_changes.md",
                output_dir / "api_changes.md",
                output_dir / "faq.md",
                output_dir / "knowledge_base.json",
            ]
        )

    if run_review:
        review_path = output_dir / "pr_review.md"
        write_markdown(review_path, pr_review_markdown(changed_files, all_api_changes))
        generated.append(review_path)

    if run_release:
        release_path = output_dir / "release_notes.md"
        write_markdown(release_path, release_notes_markdown(changed_files, all_api_changes))
        generated.append(release_path)

    if run_onboarding:
        onboarding_path = output_dir / "onboarding.md"
        write_markdown(onboarding_path, onboarding_markdown(changed_files))
        generated.append(onboarding_path)

    if run_qa:
        qa_path = output_dir / "qa_pairs.json"
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        qa_path.write_text(
            json.dumps(qa_pairs(changed_files, all_api_changes, faq_items), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        generated.append(qa_path)

    print(f"[OK] App={args.app}. Artifacts generated:")
    for path in generated:
        print(f" - {path}")
    append_usage_log(
        log_file=log_file,
        app=args.app,
        repo=repo,
        base=args.base,
        head=args.head,
        changed_files=changed_files,
        api_changes=all_api_changes,
        generated=generated,
    )
    print(f"[OK] Usage logged: {log_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
