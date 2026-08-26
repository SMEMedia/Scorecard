from __future__ import annotations

import importlib
import sys


COMMANDS = {
    "monthly": (
        "scripts.commands.run_monthly_scorecard",
        "Update the monthly Google Scorecard.",
    ),
    "weekly": (
        "scripts.commands.run_weekly_scorecard",
        "Update the weekly Google Scorecard.",
    ),
    "monthly-sources": (
        "scripts.commands.run_monthly_sources",
        "Fetch monthly sources without writing the Scorecard.",
    ),
    "weekly-sources": (
        "scripts.commands.run_weekly_sources",
        "Fetch weekly sources without writing the Scorecard.",
    ),
    "compare": (
        "scripts.tools.compare_scorecards",
        "Compare Excel sources with Google Sheets and update Discrepancies.",
    ),
    "ga4-monthly": (
        "scripts.commands.write_ga4_monthly",
        "Run the GA4-only monthly writer.",
    ),
}


def print_help() -> None:
    print("Usage: python scorecard.py <command> [options]\n")
    print("Commands:")
    width = max(len(name) for name in COMMANDS)
    for name, (_, description) in COMMANDS.items():
        print(f"  {name:<{width}}  {description}")
    print("\nRun `python scorecard.py <command> --help` for command options.")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print_help()
        return

    command = sys.argv[1]
    target = COMMANDS.get(command)
    if target is None:
        print(f"Unknown command: {command}\n", file=sys.stderr)
        print_help()
        raise SystemExit(2)

    module_name, _ = target
    sys.argv = [f"scorecard.py {command}", *sys.argv[2:]]
    module = importlib.import_module(module_name)
    module.main()


if __name__ == "__main__":
    main()
