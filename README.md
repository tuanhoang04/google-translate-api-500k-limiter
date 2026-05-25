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
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com monitoring.googleapis.com serviceconsumermanagement.googleapis.com serviceusage.googleapis.com --project YOUR_PROJECT_ID
```

---

## Step 2 — Create a service account

Create a dedicated service account for the job to run as:

```bash
gcloud iam service-accounts create YOUR_SERVICE_ACCOUNT --display-name="Translate Quota Adjuster" --project YOUR_PROJECT_ID
```

Replace `YOUR_SERVICE_ACCOUNT` with a name of your choice, e.g. `translate-quota-sa`.

---

## Step 3 — Grant roles to the service account

Grant it the roles it needs:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/monitoring.viewer" --project YOUR_PROJECT_ID

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/serviceusage.serviceUsageAdmin" --project YOUR_PROJECT_ID
```

---

## Step 4 — Build and push the container

From the folder containing `main.py`, `Dockerfile`, and `requirements.txt`:

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/translate-quota-adjuster --project YOUR_PROJECT_ID
```

---

## Step 5 — Deploy as a Cloud Run job

```bash
gcloud run jobs create translate-quota-adjuster --image gcr.io/YOUR_PROJECT_ID/translate-quota-adjuster --region asia-east1 --service-account YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com --set-env-vars GCP_PROJECT_ID=YOUR_PROJECT_ID --max-retries 2 --project YOUR_PROJECT_ID
```

To update after rebuilding:

```bash
gcloud run jobs update translate-quota-adjuster --image gcr.io/YOUR_PROJECT_ID/translate-quota-adjuster:latest --region asia-east1 --project YOUR_PROJECT_ID
```

---

## Step 6 — Create the daily schedule

Runs every day at 00:05 ICT (Asia/Ho_Chi_Minh):

```bash
gcloud scheduler jobs create http translate-quota-daily --location asia-east1 --schedule "5 0 * * *" --time-zone "Asia/Ho_Chi_Minh" --uri "https://asia-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/YOUR_PROJECT_ID/jobs/translate-quota-adjuster:run" --http-method POST --oauth-service-account-email YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com --project YOUR_PROJECT_ID
```

---

## Useful commands

**Test-trigger the scheduler manually:**
```bash
gcloud scheduler jobs run translate-quota-daily --location asia-east1 --project YOUR_PROJECT_ID
```

**Execute the Cloud Run job directly:**
```bash
gcloud run jobs execute translate-quota-adjuster --region asia-east1 --project YOUR_PROJECT_ID
```

**Check logs from the last run:**
```bash
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=translate-quota-adjuster AND resource.labels.location=asia-east1" --limit 30 --project YOUR_PROJECT_ID --order asc --format "value(textPayload)" --freshness=10m
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
