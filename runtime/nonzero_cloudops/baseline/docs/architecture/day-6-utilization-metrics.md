# Day 6: Typed Utilization Metrics

`read_utilization_metrics` is the second canonical `AUTO` / `READ_ONLY` tool. It accepts only the instance already proven by `inspect_instance` and calls only `cloudwatch:GetMetricStatistics` for `AWS/EC2` `CPUUtilization`, the `Average` statistic, and the exact instance dimension in `eu-central-1`.

The deterministic application policy uses configurable demo defaults: a 60-minute observation window, 300-second period, six required datapoints, and a 10 percent average CPU threshold. These are hackathon demo defaults, not AWS best-practice recommendations. Environment overrides use `IDLE_OBSERVATION_WINDOW_MINUTES`, `IDLE_METRIC_PERIOD_SECONDS`, `IDLE_MINIMUM_DATAPOINTS`, and `IDLE_CPU_THRESHOLD_PERCENT`.

Typed evidence retains the requested window, normalized UTC datapoints, policy values, run/trace/correlation IDs, classification, and canonical SHA-256 digest. Sufficient evidence classifies as `ELIGIBLE_CANDIDATE` or `NOT_IDLE`. Missing or insufficient data remains `AMBIGUOUS`; malformed, stale, or out-of-window data fails explicitly. No data is never interpreted as zero CPU.

No alarm, metric, tag, resource, or other AWS state is written. No deployment or live CloudWatch write occurred in this step. A candidate finding is evidence only and does not authorize remediation.
