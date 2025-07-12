#!/bin/bash

# Configuration - CHANGE THESE VALUES FOR YOUR PROJECT
PROJECT_ID="data-etl-to-bigquery"     # Your Google Cloud project ID
REGION="us-central1"                  # Your preferred region
JOB_NAME="ctm-batch-job"              # Your descriptive job name
IMAGE_NAME="gcr.io/$PROJECT_ID/$JOB_NAME"
SCHEDULER_JOB_NAME="ctm-batch-job-scheduler"  # Your schedule name (if needed later)

echo "🚀 Smart deployment for CTM batch job..."

# Step 1: Set the project
echo "🔧 Setting project..."
gcloud config set project $PROJECT_ID

# Step 2: Enable required APIs
echo "🔌 Enabling required APIs..."
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable cloudscheduler.googleapis.com

# Step 3: Always build and push the latest image
echo "📦 Building latest container image..."
gcloud builds submit --tag $IMAGE_NAME .

# Step 4: Smart job deployment (create or update)
echo "🚢 Deploying Cloud Run job..."
if gcloud run jobs describe $JOB_NAME --region=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo "🔄 Job exists, updating with latest image..."
    gcloud run jobs update $JOB_NAME \
      --image=$IMAGE_NAME \
      --region=$REGION \
      --project=$PROJECT_ID \
      --memory=2Gi \
      --cpu=1 \
      --max-retries=3 \
      --task-timeout=3600 \
      --parallelism=1 
      
else
    echo "🆕 Job doesn't exist, creating new job..."
    gcloud run jobs create $JOB_NAME \
      --image=$IMAGE_NAME \
      --region=$REGION \
      --project=$PROJECT_ID \
      --memory=2Gi \
      --cpu=1 \
      --max-retries=3 \
      --task-timeout=3600 \
      --parallelism=1 
   
fi

# Step 5: Smart scheduler setup (create or update) - COMMENTED OUT FOR BATCH JOB
# echo "⏰ Setting up daily schedule..."
# if gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$REGION &>/dev/null; then
#     echo "🔄 Schedule exists, updating..."
#     gcloud scheduler jobs update http $SCHEDULER_JOB_NAME \
#         --location=$REGION \
#         --schedule="0 0 * * *" \
#         --time-zone="UTC" \
#         --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB_NAME:run" \
#         --http-method=POST \
#         --oauth-service-account-email="$PROJECT_ID@appspot.gserviceaccount.com" \
#         --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
# else
#     echo "🆕 Schedule doesn't exist, creating new schedule..."
#     gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
#         --location=$REGION \
#         --schedule="0 0 * * *" \
#         --time-zone="UTC" \
#         --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB_NAME:run" \
#         --http-method=POST \
#         --oauth-service-account-email="$PROJECT_ID@appspot.gserviceaccount.com" \
#         --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
#         --description="Daily Batch sync at 12:00 AM UTC"
# fi

echo ""
echo "🎉 Smart deployment complete!"
echo ""
echo "📋 What happened:"
echo "✅ Built latest image with your code changes"
echo "✅ Updated/created Cloud Run job: $JOB_NAME"
echo "⚠️  No scheduler created (batch job - run manually as needed)"
echo ""
echo "🔍 Useful commands:"
echo "📊 View logs: gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --limit=20"
echo "⏰ View schedule: gcloud scheduler jobs list --location=$REGION"
echo "🏃 Run job manually: gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "💡 Next time you update code, just run: ./deploy.sh"
echo "💡 To run the batch job: gcloud run jobs execute $JOB_NAME --region=$REGION"