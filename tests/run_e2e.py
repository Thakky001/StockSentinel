#!/usr/bin/env python3
"""
StockSentinel Unified E2E Test Runner.
Executes the comprehensive 4-Tier test suite covering Features 1-36.
Supports filtering by Tier, Feature ID, JSON output, and CLI exit codes.

Usage:
  python tests/run_e2e.py                   # Run full test suite across all 4 tiers
  python tests/run_e2e.py --tier 1          # Run Tier 1 Isolation Coverage only
  python tests/run_e2e.py --tier 2          # Run Tier 2 Boundary Tests only
  python tests/run_e2e.py --tier 3          # Run Tier 3 Pairwise Interactions only
  python tests/run_e2e.py --tier 4          # Run Tier 4 Real-World Workflows only
  python tests/run_e2e.py --feature 12      # Run tests covering Feature 12 (Resampling)
  python tests/run_e2e.py --json            # Output machine-readable JSON report
  python tests/run_e2e.py -v                # Verbose mode
"""

import sys
import os
import argparse
import unittest
import time
import json
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def get_tier_modules(tier: str):
    """Returns mapping of modules per requested tier."""
    modules = {
        "1": [
            "tests.e2e.tier1_features.test_f01_f06_database",
            "tests.e2e.tier1_features.test_f07_f11_universe_ingest",
            "tests.e2e.tier1_features.test_f12_f20_screener_math",
            "tests.e2e.tier1_features.test_f21_f23_telegram",
            "tests.e2e.tier1_features.test_f24_f30_backend_api",
            "tests.e2e.tier1_features.test_f31_f36_frontend_calc",
        ],
        "2": [
            "tests.e2e.tier2_boundaries.test_t2_database_boundaries",
            "tests.e2e.tier2_boundaries.test_t2_universe_boundaries",
            "tests.e2e.tier2_boundaries.test_t2_challenger_sync_coordination",
            "tests.e2e.tier2_boundaries.test_t2_indicators_boundaries",
            "tests.e2e.tier2_boundaries.test_t2_challenger_m3_screener_stress",
            "tests.e2e.tier2_boundaries.test_t2_telegram_boundaries",
            "tests.e2e.tier2_boundaries.test_t2_api_boundaries",
            "tests.e2e.tier2_boundaries.test_t2_frontend_calc_boundaries",
        ],
        "3": [
            "tests.e2e.tier3_interactions.test_t3_ingest_to_screener",
            "tests.e2e.tier3_interactions.test_t3_screener_to_telegram",
            "tests.e2e.tier3_interactions.test_t3_database_to_api",
            "tests.e2e.tier3_interactions.test_t3_api_to_frontend_chart",
        ],
        "4": [
            "tests.e2e.tier4_scenarios.test_t4_cold_start_to_dashboard",
            "tests.e2e.tier4_scenarios.test_t4_weekly_delta_breakout_flow",
            "tests.e2e.tier4_scenarios.test_t4_market_holiday_resampling_flow",
            "tests.e2e.tier4_scenarios.test_t4_telegram_alert_flood_flow",
            "tests.e2e.tier4_scenarios.test_t4_investor_risk_workflow",
        ]
    }
    if tier == "all":
        return [m for sublist in modules.values() for m in sublist]
    return modules.get(str(tier), [])


def filter_tests_by_feature(suite: unittest.TestSuite, feature_id: int) -> unittest.TestSuite:
    """Filters test suite to only test cases matching feature ID pattern."""
    feature_tag = f"f{feature_id:02d}"
    filtered = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            sub_filtered = filter_tests_by_feature(test, feature_id)
            if sub_filtered.countTestCases() > 0:
                filtered.addTest(sub_filtered)
        else:
            test_id = test.id().lower()
            if feature_tag in test_id or f"feature_{feature_id}" in test_id or f"f{feature_id}_" in test_id:
                filtered.addTest(test)
    return filtered


def run_e2e_suite():
    parser = argparse.ArgumentParser(description="StockSentinel E2E Test Suite Runner")
    parser.add_argument("--tier", choices=["1", "2", "3", "4", "all"], default="all", help="Target test tier")
    parser.add_argument("--feature", type=int, help="Target feature ID (1-36)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose test execution")
    parser.add_argument("--failfast", action="store_true", help="Stop on first error or failure")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON report")
    args = parser.parse_args()

    module_names = get_tier_modules(args.tier)
    loader = unittest.TestLoader()
    master_suite = unittest.TestSuite()

    for mod_name in module_names:
        try:
            mod_suite = loader.loadTestsFromName(mod_name)
            master_suite.addTest(mod_suite)
        except Exception as e:
            print(f"[ERROR] Failed to load test module {mod_name}: {e}", file=sys.stderr)

    if args.feature is not None:
        master_suite = filter_tests_by_feature(master_suite, args.feature)

    total_tests = master_suite.countTestCases()

    if not args.json:
        print("=" * 80)
        print(" StockSentinel Comprehensive E2E Test Suite")
        print(f" Target Tier: {args.tier.upper()} | Feature Filter: {args.feature or 'All (1-36)'}")
        print(f" Total Tests Discovered: {total_tests}")
        print("=" * 80)

    start_time = time.time()
    runner = unittest.TextTestRunner(
        verbosity=2 if args.verbose else (0 if args.json else 1),
        failfast=args.failfast
    )
    result = runner.run(master_suite)
    elapsed = time.time() - start_time

    passed = result.testsRun - len(result.failures) - len(result.errors)
    success = result.wasSuccessful()

    if args.json:
        report = {
            "success": success,
            "tier": args.tier,
            "feature": args.feature,
            "total_tests": result.testsRun,
            "passed": passed,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "duration_seconds": round(elapsed, 3),
            "failure_details": [
                {"test": str(test), "traceback": trace} for test, trace in result.failures
            ],
            "error_details": [
                {"test": str(test), "traceback": trace} for test, trace in result.errors
            ]
        }
        print(json.dumps(report, indent=2))
    else:
        print("\n" + "=" * 80)
        print(" E2E Test Execution Summary")
        print("=" * 80)
        print(f" Status:          {'PASS [OK]' if success else 'FAIL [X]'}")
        print(f" Total Executed:  {result.testsRun}")
        print(f" Passed:          {passed}")
        print(f" Failures:        {len(result.failures)}")
        print(f" Errors:          {len(result.errors)}")
        print(f" Time Elapsed:    {elapsed:.3f}s")
        print("=" * 80)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(run_e2e_suite())
