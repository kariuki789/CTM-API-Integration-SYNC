import logging
import base64
import requests
import pandas as pd
import sys
import os
from datetime import datetime
from google.cloud import bigquery
from google.auth import default
from pandas_gbq import to_gbq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# -------------------------
# Logging setup for Cloud Run
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# -------------------------
# Environment Variable Helper
# -------------------------
def get_env_var(var_name, required=True):
    """Get environment variable with optional requirement check"""
    value = os.environ.get(var_name)
    if required and not value:
        logger.error(f"Required environment variable {var_name} is not set")
        sys.exit(1)
    return value

# -------------------------
# Configuration from Environment Variables
# -------------------------
ACCESS_KEY = get_env_var('CTM_ACCESS_KEY')
SECRET_KEY = get_env_var('CTM_SECRET_KEY')
PROJECT_ID = get_env_var('PROJECT_ID', required=False) or "data-etl-to-bigquery"
DATASET_ID = "ctm_data"
TABLE_ID = "accounts"
DESTINATION_TABLE = f"{DATASET_ID}.{TABLE_ID}"
CTM_URL = "https://api.calltrackingmetrics.com/api/v1/accounts"

# -------------------------
# Auth Setup
# -------------------------
credentials, _ = default()
bq_client = bigquery.Client(project=PROJECT_ID, credentials=credentials)

# -------------------------
# Helper Functions
# -------------------------
def build_auth_headers():
    """Build authentication headers for CTM API"""
    auth_string = f"{ACCESS_KEY}:{SECRET_KEY}"
    auth_bytes = auth_string.encode("ascii")
    auth_b64 = base64.b64encode(auth_bytes).decode("ascii")
    return {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/json"
    }

def fetch_all_accounts():
    """Fetch all accounts from CTM API with pagination"""
    headers = build_auth_headers()
    all_accounts = []
    url = CTM_URL
    params = {'per_page': 100}

    while url:
        logger.info(f"Fetching accounts from: {url}")
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            logger.error(f"❌ Failed to fetch accounts. Status {response.status_code}: {response.text}")
            raise Exception(f"API request failed with status {response.status_code}")

        data = response.json()
        accounts = data.get("accounts", [])
        all_accounts.extend(accounts)
        
        logger.info(f"Fetched {len(accounts)} accounts from this page. Total so far: {len(all_accounts)}")

        url = data.get("next_page")
        if url:
            params = None  # next_page contains full query params, so disable params on next call

    return all_accounts

def process_accounts_data(accounts):
    """Process and clean accounts data"""
    if not accounts:
        logger.warning("⚠️ No account data to process.")
        return None

    df = pd.DataFrame(accounts)
    columns_to_keep = ["id", "name", "user_role", "status", "created", "updated", "canceled", "agency_id"]
    
    # Keep only existing columns to avoid KeyError
    existing_columns = [col for col in columns_to_keep if col in df.columns]
    df = df[existing_columns]

    # Convert timestamp columns
    timestamp_columns = ["created", "updated", "canceled"]
    for col in timestamp_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df

def upload_to_bigquery(df):
    """Upload DataFrame to BigQuery"""
    logger.info(f"⬆️ Uploading {len(df)} account records to BigQuery table: {DESTINATION_TABLE}")
    
    to_gbq(
        df,
        destination_table=DESTINATION_TABLE,
        project_id=PROJECT_ID,
        if_exists="replace",
        progress_bar=False
    )
    
    logger.info("✅ Data successfully loaded to BigQuery.")

# -------------------------
# Main Job Function
# -------------------------
def main():
    start_time = datetime.now()
    
    # Log job start with structured logging
    logger.info("JOB_START: CTM Accounts sync job initiated", extra={
        'job_name': 'ctm_accounts_sync',
        'status': 'STARTED',
        'timestamp': start_time.isoformat()
    })

    try:
        logger.info("🚀 CTM Accounts sync job starting...")
        
        # Fetch all accounts from CTM API
        logger.info("📡 Fetching accounts from CTM API...")
        accounts = fetch_all_accounts()
        
        if not accounts:
            logger.warning("⚠️ No account data returned from CTM API.")
            logger.info("JOB_SUCCESS: CTM Accounts sync completed with no data", extra={
                'job_name': 'ctm_accounts_sync',
                'status': 'SUCCESS',
                'total_accounts': 0,
                'processing_time_seconds': (datetime.now() - start_time).total_seconds(),
                'timestamp': datetime.now().isoformat()
            })
            return

        # Process the data
        logger.info(f"📊 Processing {len(accounts)} accounts...")
        df = process_accounts_data(accounts)
        
        if df is None or df.empty:
            logger.warning("⚠️ No valid account data to upload.")
            return

        # Upload to BigQuery
        upload_to_bigquery(df)

        # Calculate processing time
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        # Log successful completion
        logger.info("JOB_SUCCESS: CTM Accounts sync completed successfully", extra={
            'job_name': 'ctm_accounts_sync',
            'status': 'SUCCESS',
            'total_accounts': len(accounts),
            'processed_accounts': len(df),
            'processing_time_seconds': round(processing_time, 2),
            'timestamp': end_time.isoformat()
        })

    except Exception as e:
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        # Log failure
        logger.error("JOB_FAILURE: CTM Accounts sync failed", extra={
            'job_name': 'ctm_accounts_sync',
            'status': 'FAILED',
            'error_message': str(e),
            'processing_time_seconds': round(processing_time, 2),
            'timestamp': end_time.isoformat()
        }, exc_info=True)
        
        # Re-raise so Cloud Run marks job as failed
        raise

if __name__ == '__main__':
    main()