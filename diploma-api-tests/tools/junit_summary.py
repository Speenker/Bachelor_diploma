from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class TestCaseResult:
    full_name: str
    seconds: float
    status: str  # passed|failed|error|skipped|xfailed
    message: str | None = None
    kind: str | None = None


def _parse_seconds(raw: str | None) -> float:
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _format_duration(seconds: float) -> str:
    rounded = round(seconds, 3)
    td = dt.timedelta(seconds=int(round(seconds)))
    return f"{rounded:.3f}s ({td})"


def _discover_testsuites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        return list(root.findall("testsuite"))
    return list(root.findall(".//testsuite"))


def parse_junit(path: Path) -> tuple[list[TestCaseResult], dict[str, str | float | int]]:
    tree = ET.parse(path)
    root = tree.getroot()

    suites = _discover_testsuites(root)
    if not suites:
        raise ValueError("No <testsuite> elements found")

    results: list[TestCaseResult] = []

    total_time_seconds = 0.0
    timestamp: str | None = None

    for suite in suites:
        total_time_seconds += _parse_seconds(suite.get("time"))
        if timestamp is None:
            timestamp = suite.get("timestamp")

        for tc in suite.findall(".//testcase"):
            classname = (tc.get("classname") or "").strip()
            name = (tc.get("name") or "").strip()
            full_name = f"{classname}::{name}" if classname else name
            seconds = _parse_seconds(tc.get("time"))

            error_el = tc.find("error")
            failure_el = tc.find("failure")
            skipped_el = tc.find("skipped")

            if error_el is not None:
                results.append(
                    TestCaseResult(
                        full_name=full_name,
                        seconds=seconds,
                        status="error",
                        message=error_el.get("message") or (error_el.text or "").strip() or None,
                        kind=error_el.get("type"),
                    )
                )
                continue

            if failure_el is not None:
                results.append(
                    TestCaseResult(
                        full_name=full_name,
                        seconds=seconds,
                        status="failed",
                        message=failure_el.get("message") or (failure_el.text or "").strip() or None,
                        kind=failure_el.get("type"),
                    )
                )
                continue

            if skipped_el is not None:
                skipped_type = skipped_el.get("type")
                message = skipped_el.get("message") or (skipped_el.text or "").strip() or None
                status = "xfailed" if skipped_type == "pytest.xfail" else "skipped"
                results.append(
                    TestCaseResult(
                        full_name=full_name,
                        seconds=seconds,
                        status=status,
                        message=message,
                        kind=skipped_type,
                    )
                )
                continue

            results.append(TestCaseResult(full_name=full_name, seconds=seconds, status="passed"))

    counts = {
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "passed"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "errors": sum(1 for r in results if r.status == "error"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "xfailed": sum(1 for r in results if r.status == "xfailed"),
        "duration_seconds": total_time_seconds,
        "timestamp": timestamp or "",
    }

    return results, counts


def render_text(
    junit_path: Path,
    results: list[TestCaseResult],
    counts: dict[str, str | float | int],
    top_slowest: int,
) -> str:
    duration_seconds = float(counts["duration_seconds"])
    timestamp = str(counts["timestamp"]).strip()

    lines: list[str] = []
    lines.append(f"JUnit: {junit_path}")
    if timestamp:
        lines.append(f"Timestamp: {timestamp}")
    lines.append(f"Duration: {_format_duration(duration_seconds)}")
    lines.append("")

    lines.append(
        "Total: {total} | Passed: {passed} | XFailed: {xfailed} | Skipped: {skipped} | Failed: {failed} | Errors: {errors}".format(
            total=counts["total"],
            passed=counts["passed"],
            xfailed=counts["xfailed"],
            skipped=counts["skipped"],
            failed=counts["failed"],
            errors=counts["errors"],
        )
    )

    xfail_reasons = sorted({r.message for r in results if r.status == "xfailed" and r.message})
    if xfail_reasons:
        lines.append("")
        lines.append("XFAIL reasons:")
        for reason in xfail_reasons:
            lines.append(f"- {reason}")

    if top_slowest > 0:
        slowest = sorted(results, key=lambda r: r.seconds, reverse=True)[:top_slowest]
        lines.append("")
        lines.append(f"Top {len(slowest)} slowest testcases:")
        for r in slowest:
            status = r.status.upper()
            lines.append(f"- {r.full_name} - {r.seconds:.3f}s ({status})")

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Render a short, human-friendly summary from pytest JUnit XML.",
    )
    parser.add_argument(
        "--junit",
        required=True,
        help="Path to JUnit XML file produced by pytest --junitxml.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output file path to write the summary to.",
    )
    parser.add_argument(
        "--top-slowest",
        type=int,
        default=5,
        help="How many slowest testcases to include (default: 5).",
    )

    args = parser.parse_args(argv)

    junit_path = Path(args.junit).expanduser().resolve()
    if not junit_path.exists():
        print(f"ERROR: JUnit file not found: {junit_path}", file=sys.stderr)
        return 2

    results, counts = parse_junit(junit_path)
    text = render_text(junit_path, results, counts, top_slowest=max(0, int(args.top_slowest)))

    print(text, end="")

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
