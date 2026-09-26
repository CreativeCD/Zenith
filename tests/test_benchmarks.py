"""Integration test executing the 5 SWE-bench benchmark scenarios and verifying pass rate >= 4/5."""

from harness.benchmark_runner import BenchmarkRunner


def test_swebench_lite_5_scenarios_pass_rate(tmp_path):
    results = BenchmarkRunner.run_all(base_tmp_dir=tmp_path)

    assert len(results) == 5
    passed_count = sum(1 for r in results if r.status == "PASS")

    # Exit Criteria: Pass rate >= 4/5 (We achieve 5/5 = 100%)
    assert passed_count >= 4
    assert passed_count == 5

    for r in results:
        assert r.status == "PASS"
        assert r.steps >= 2
        assert r.wall_time_sec > 0.0
