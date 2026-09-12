"""Narrow provider protocol for one EC2 CPU utilization read."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol


class CloudWatchGetMetricStatisticsClient(Protocol):
    """Only the scoped GetMetricStatistics call required by the demo policy."""

    def get_metric_statistics(
        self,
        *,
        Namespace: str,
        MetricName: str,
        Dimensions: list[dict[str, str]],
        StartTime: datetime,
        EndTime: datetime,
        Period: int,
        Statistics: list[str],
        Unit: str,
    ) -> Mapping[str, Any]:
        """Read one fixed metric for one exact validated instance."""
