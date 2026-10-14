"""CloudWatch metrics via the Embedded Metric Format.

Inside Lambda, one JSON line on stdout becomes a metric - no PutMetricData
call, no extra IAM permission. Outside Lambda this is a no-op so local runs
and tests stay quiet.
"""

from __future__ import annotations

import json
import os
import time


def emit(metrics: dict[str, float], dimensions: dict[str, str] | None = None) -> None:
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return
    dimensions = dimensions or {}
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": os.environ.get("METRICS_NAMESPACE", "DayAhead"),
                            "Dimensions": [list(dimensions)],
                            "Metrics": [{"Name": name} for name in metrics],
                        }
                    ],
                },
                **dimensions,
                **metrics,
            }
        )
    )
