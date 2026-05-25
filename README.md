# Google Translate Quota Adjuster — Setup Guide

## What it does

A Cloud Run job runs every day at 00:05 Vietnam time and:
1. Reads your Translate API character usage this month from Cloud Monitoring
2. Calculates a new daily limit: `(500,000 − used so far) ÷ days remaining`
3. Updates your project-level quota override via the Service Usage API

---

## Prerequisites

- `gcloud` CLI installed and authenticated as your personal Google account
- Billing enabled on your project
- Google Translate API already enabled
- Note: run all commands with impersonation **off** unless stated otherwise

---

## Step 1 — Enable required APIs

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com monitoring.googleapis.com serviceconsumermanagement.googleapis.com serviceusage.googleapis.com --project translate-project-469204
```

---

## Step 2 — Grant roles to the service account

The job runs as `translate-quota-sa`. Grant it the roles it needs:

```bash
gcloud projects add-iam-policy-binding translate-project-469204 --member="serviceAccount:translate-quota-sa@translate-project-469204.iam.gserviceaccount.com" --role="roles/monitoring.viewer" --project translate-project-469204

gcloud projects add-iam-policy-binding translate-project-469204 --member="serviceAccount:translate-quota-sa@translate-project-469204.iam.gserviceaccount.com" --role="roles/serviceusage.serviceUsageAdmin" --project translate-project-469204
```

---

## Step 3 — Build and push the container

From the folder containing `main.py`, `Dockerfile`, and `requirements.txt`:

```bash
gcloud builds submit --tag gcr.io/translate-project-469204/translate-quota-adjuster --project translate-project-469204
```

---

## Step 4 — Deploy as a Cloud Run job

```bash
gcloud run jobs create translate-quota-adjuster --image gcr.io/translate-project-469204/translate-quota-adjuster --region asia-east1 --service-account translate-quota-sa@translate-project-469204.iam.gserviceaccount.com --set-env-vars GCP_PROJECT_ID=translate-project-469204 --max-retries 2 --project translate-project-469204
```

To update after rebuilding:

```bash
gcloud run jobs update translate-quota-adjuster --image gcr.io/translate-project-469204/translate-quota-adjuster:latest --region asia-east1 --project translate-project-469204
```

---

## Step 5 — Create the daily schedule

Runs every day at 00:05 ICT (Asia/Ho_Chi_Minh):

```bash
gcloud scheduler jobs create http translate-quota-daily --location asia-east1 --schedule "5 0 * * *" --time-zone "Asia/Ho_Chi_Minh" --uri "https://asia-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/translate-project-469204/jobs/translate-quota-adjuster:run" --http-method POST --oauth-service-account-email translate-quota-sa@translate-project-469204.iam.gserviceaccount.com --project translate-project-469204
```

---

## Useful commands

**Test-trigger the scheduler manually:**
```bash
gcloud scheduler jobs run translate-quota-daily --location asia-east1 --project translate-project-469204
```

**Execute the Cloud Run job directly:**
```bash
gcloud run jobs execute translate-quota-adjuster --region asia-east1 --project translate-project-469204
```

**Check logs from the last run:**
```bash
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=translate-quota-adjuster AND resource.labels.location=asia-east1" --limit 30 --project translate-project-469204 --order asc --format "value(textPayload)" --freshness=10m
```

**Verify quota override in Cloud Console:**
APIs & Services → Cloud Translation API → Quotas → look for "Characters per day"

---

## How the formula works

```
daily limit = (500,000 − chars used this month) ÷ days remaining in month
```

On the 1st of each month with zero usage: `500,000 ÷ 31 ≈ 16,129 chars/day`.

If you use less than the limit on any day, the unused quota rolls forward and the next day's limit increases automatically.

If Cloud Monitoring has no usage data yet (first run of the month, or metrics haven't propagated — up to 3 hours after first API call), the script assumes 0 used and sets the maximum safe limit for the remaining days.

---

## Quota metric used

The override targets: `translate.googleapis.com/default`
Description: v2 and v3 general model characters, per day per project.
This is the quota that counts against your 500,000 character/month free tier.
