"""
Google Translate daily quota adjuster.
Runs as a Cloud Run job triggered by Cloud Scheduler.

Formula: dailyLimit = (500_000 - totalUsedThisMonth) / remainingDaysInMonth

Quota limit: translate.googleapis.com/default — "v2 and v3 general model characters"
Limit path:  .../limits/%2Fd%2Fproject  (characters per day per project)
"""

import os
import math
import calendar
from datetime import datetime, timezone

import requests
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import monitoring_v3


PROJECT_ID = os.environ["GCP_PROJECT_ID"]
MONTHLY_CAP = 500_000
BASE = "https://serviceusage.googleapis.com/v1beta1"

# Exact resource path discovered from the API
LIMIT_NAME = (
    "projects/{project_id}/services/translate.googleapis.com"
    "/consumerQuotaMetrics/translate.googleapis.com%2Fdefault"
    "/limits/%2Fd%2Fproject"
)


def get_token() -> str:
    credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())
    return credentials.token


def get_month_usage(project_id: str) -> int:
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    interval = monitoring_v3.TimeInterval({
        "end_time": {"seconds": int(now.timestamp())},
        "start_time": {"seconds": int(month_start.timestamp())},
    })
    candidates = [
        'metric.type="serviceruntime.googleapis.com/quota/allocation/usage" resource.labels.service="translate.googleapis.com"',
        'metric.type="serviceruntime.googleapis.com/quota/rate/net_usage" resource.labels.service="translate.googleapis.com"',
    ]
    for filter_str in candidates:
        try:
            total = 0
            for series in client.list_time_series(request={
                "name": project_name,
                "filter": filter_str,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }):
                for point in series.points:
                    val = point.value.int64_value or int(point.value.double_value)
                    total += max(0, val)
            if total > 0:
                print(f"  [monitoring] Usage found: {total:,} chars")
                return total
        except Exception as e:
            print(f"  [monitoring] Skipping ({type(e).__name__}): {str(e)[:100]}")
    print("  [monitoring] No usage data — treating as 0 used this month.")
    return 0


def calculate_daily_limit(total_used: int) -> int:
    now = datetime.now(timezone.utc)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    remaining_days = days_in_month - now.day + 1
    remaining_quota = max(0, MONTHLY_CAP - total_used)
    if remaining_days <= 0:
        return 0
    return math.floor(remaining_quota / remaining_days)


def set_quota_override(project_id: str, daily_limit: int, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"overrideValue": str(daily_limit)}
    limit_name = LIMIT_NAME.format(project_id=project_id)
    overrides_url = f"{BASE}/{limit_name}/consumerOverrides"

    # Check for existing override to PATCH, otherwise POST to create
    list_resp = requests.get(overrides_url, headers=headers)
    existing = list_resp.json().get("overrides", []) if list_resp.ok else []

    if existing:
        override_name = existing[0]["name"]
        print(f"  [quota] Patching existing override: {override_name.split('/')[-1]}")
        resp = requests.patch(
            f"{BASE}/{override_name}",
            headers=headers,
            json=body,
            params={"force": "true"},
        )
    else:
        print(f"  [quota] Creating new override...")
        resp = requests.post(
            overrides_url,
            headers=headers,
            json=body,
            params={"force": "true"},
        )

    if resp.status_code in (200, 201):
        return resp.json()

    raise RuntimeError(f"Quota override failed ({resp.status_code}): {resp.text[:400]}")


def main():
    print(f"[quota-adjuster] Starting — project: {PROJECT_ID}")

    token = get_token()
    total_used = get_month_usage(PROJECT_ID)
    daily_limit = calculate_daily_limit(total_used)

    now = datetime.now(timezone.utc)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    remaining_days = days_in_month - now.day + 1

    print(f"  Month cap        : {MONTHLY_CAP:,}")
    print(f"  Used this month  : {total_used:,}")
    print(f"  Remaining quota  : {MONTHLY_CAP - total_used:,}")
    print(f"  Days remaining   : {remaining_days}")
    print(f"  → New daily limit: {daily_limit:,} chars/day")

    result = set_quota_override(PROJECT_ID, daily_limit, token)
    print(f"  Operation: {result.get('name', str(result))[:120]}")
    print("[quota-adjuster] Done.")


if __name__ == "__main__":
    main()
