import base64
import requests
import pandas as pd
from pandas_gbq import to_gbq
from google.cloud import bigquery
import re
import time
import json
import datetime
import logging
from google.auth import default

import os
import sys

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
# Configuration - Get from environment variables
# -------------------------
def get_env_var(var_name, required=True):
    """Get environment variable with optional requirement check"""
    value = os.environ.get(var_name)
    if required and not value:
        logger.error(f"Required environment variable {var_name} is not set")
        sys.exit(1)
    return value

# CTM API credentials from environment variables (Secret Manager)
access_key = get_env_var('CTM_ACCESS_KEY')
secret_key = get_env_var('CTM_SECRET_KEY')

# BigQuery config
project_id = get_env_var('PROJECT_ID', required=False) or 'data-etl-to-bigquery'

dataset_id = 'ctm_data'

# Basic Auth header
auth_string = f"{access_key}:{secret_key}"
auth_bytes = auth_string.encode('ascii')
auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
headers = {
    'Authorization': f'Basic {auth_b64}',
    'Content-Type': 'application/json'
}

# Rate limit config
REQUESTS_PER_SECOND = 8
SLEEP_SECONDS = 1.0 / REQUESTS_PER_SECOND

def fetch_all_calls_for_account(account_id):
    base_url = f'https://api.calltrackingmetrics.com/api/v1/accounts/{account_id}/calls'
    all_calls = []
    url = base_url
    params = {'per_page': 100}

    while url:
        print(f"    Fetching page for account {account_id}")
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"    Error {response.status_code} for account {account_id}")
            break
        data = response.json()
        all_calls.extend(data.get('calls', []))
        url = data.get('next_page')
        params = None
        time.sleep(SLEEP_SECONDS)
    
    print(f"    Found {len(all_calls)} calls for account {account_id}")
    return all_calls

def get_all_accounts():
    """Get all accounts ordered by ID"""
    client = bigquery.Client(project=project_id)
    query = f"""
    SELECT id, name
    FROM `{project_id}.{dataset_id}.accounts`
    ORDER BY id ASC
    """
    results = client.query(query).result()
    return [(row.id, row.name) for row in results]

def get_existing_batch_tables():
    """Get list of existing batch tables"""
    client = bigquery.Client(project=project_id)
    try:
        dataset = client.get_dataset(f"{project_id}.{dataset_id}")
        tables = list(client.list_tables(dataset))
        batch_tables = [table.table_id for table in tables if table.table_id.startswith('activities_raw_batch_')]
        return batch_tables
    except Exception as e:
        print(f"Could not get existing tables: {str(e)}")
        return []

def get_next_batch_info():
    """Determine which batch to process next"""
    all_accounts = get_all_accounts()
    existing_batches = get_existing_batch_tables()
    
    print(f"Total accounts: {len(all_accounts)}")
    print(f"Existing batch tables: {existing_batches}")
    
    # Calculate batch number
    batch_num = len(existing_batches) + 1
    accounts_per_batch = 60
    
    # Calculate account range for this batch
    start_idx = (batch_num - 1) * accounts_per_batch
    end_idx = min(start_idx + accounts_per_batch, len(all_accounts))
    
    if start_idx >= len(all_accounts):
        return None, [], 0, 0  # No more batches needed
    
    batch_accounts = all_accounts[start_idx:end_idx]
    
    return batch_num, batch_accounts, start_idx, end_idx

def clean_column_name(col):
    col = re.sub(r'[^a-zA-Z0-9_]', '_', col)
    if not re.match(r'^[a-zA-Z_]', col):
        col = '_' + col
    return col.lower()

def main():
    print("🚀 Starting batch table generator")
    
    # Get next batch info
    batch_num, accounts, start_idx, end_idx = get_next_batch_info()
    
    if batch_num is None:
        print("✅ All batches have been completed!")
        print("\n🔗 Ready to join tables! Use this SQL:")
        print(f"""
        CREATE OR REPLACE TABLE `{project_id}.{dataset_id}.activities_raw_combined` AS
        SELECT *, 1 as batch_number FROM `{project_id}.{dataset_id}.activities_raw_batch_1`
        UNION ALL
        SELECT *, 2 as batch_number FROM `{project_id}.{dataset_id}.activities_raw_batch_2`
        UNION ALL
        SELECT *, 3 as batch_number FROM `{project_id}.{dataset_id}.activities_raw_batch_3`
        UNION ALL
        SELECT *, 4 as batch_number FROM `{project_id}.{dataset_id}.activities_raw_batch_4`
        UNION ALL
        SELECT *, 5 as batch_number FROM `{project_id}.{dataset_id}.activities_raw_batch_5`
        -- Add more as needed
        """)
        return
    
    # Create batch table name
    batch_table_name = f"activities_raw_batch_{batch_num}"
    destination_table = f"{dataset_id}.{batch_table_name}"
    
    print(f"\n📊 Processing Batch {batch_num}")
    print(f"📋 Table: {batch_table_name}")
    print(f"👥 Accounts: {start_idx + 1} to {end_idx} ({len(accounts)} accounts)")
    print(f"📝 Account range: {accounts[0][0]} to {accounts[-1][0]}")
    
    print(f"\n📊 Processing {len(accounts)} accounts:")
    for acc_id, name in accounts[:5]:  # Show first 5
        print(f"  - {acc_id}: {name}")
    if len(accounts) > 5:
        print(f"  ... and {len(accounts) - 5} more")
    
    all_calls = []
    for account_id, account_name in accounts:
        print(f"\nProcessing account {account_id} - {account_name}")
        calls = fetch_all_calls_for_account(account_id)

        # Add account info and batch info
        for call in calls:
            call['account_id'] = account_id
            call['account_name'] = account_name
            call['batch_number'] = batch_num
            call['processed_at'] = datetime.datetime.utcnow().isoformat()

            # Convert nested objects/lists to JSON string
            for k, v in call.items():
                if isinstance(v, (dict, list)):
                    call[k] = json.dumps(v)

        all_calls.extend(calls)

    print(f"\n📈 Total calls fetched for batch {batch_num}: {len(all_calls)}")

    if not all_calls:
        print(f"No calls fetched for batch {batch_num}")
        return

    df = pd.json_normalize(all_calls)

    # Convert timestamps
    for date_col in ['called_at', 'billed_at']:
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce', utc=True)

    # Clean columns for BigQuery
    df.columns = [clean_column_name(c) for c in df.columns]

    print(f"DataFrame shape: {df.shape}")
    print(f"Columns: {len(df.columns)}")

    # Always use 'replace' for batch tables (each is independent)
    to_gbq(df, destination_table, project_id=project_id, if_exists='replace')
    
    print(f"✅ Batch {batch_num} uploaded to {destination_table}")
    
    # Show what's next
    next_batch_num, next_accounts, next_start, next_end = get_next_batch_info()
    if next_batch_num:
        print(f"\n⏭️  Next: Batch {next_batch_num} ({len(next_accounts)} accounts)")
        print("💡 Run this job again to process the next batch")
    else:
        total_batches = batch_num
        print(f"\n🎉 BATCH {batch_num} COMPLETED!")
        print(f"📊 Total batches created: {total_batches}")
        print("\n🔗 Ready to join all tables with SQL!")

if __name__ == '__main__':
    main()