"""CLI entrypoint for the Scrapling Reddit Spider.

Run via Docker or directly:
    python handler.py --subreddit-url "https://www.reddit.com/r/Python/new/" \
                      --gcs-output-path "gs://my-bucket/reddit-data/"

GCP credentials are resolved via:
  1. --credentials flag (path to SA JSON key)
  2. GOOGLE_APPLICATION_CREDENTIALS env var
  3. GCP metadata server (when running on Cloud Run Jobs)
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def upload_to_gcs(data: list, gcs_output_path: str):
    """Upload scraped data as JSON files to a GCS path.

    Args:
        data: List of scraped post dicts
        gcs_output_path: Full GCS path like gs://bucket/prefix/
    """
    from google.cloud import storage

    path = gcs_output_path.replace("gs://", "")
    parts = path.split("/", 1)
    bucket_name = parts[0]
    prefix = parts[1].rstrip("/") if len(parts) > 1 else ""

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    uploaded_files = []
    for item in data:
        post_id = item.get("post_id", "unknown")
        blob_path = f"{prefix}/{timestamp}/post_{post_id}.json" if prefix else f"{timestamp}/post_{post_id}.json"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(item, indent=2, ensure_ascii=False),
            content_type="application/json",
        )
        uploaded_files.append(f"gs://{bucket_name}/{blob_path}")
        logger.info(f"Uploaded {blob_path}")

    # Upload a summary manifest
    summary = {
        "timestamp": timestamp,
        "total_posts": len(data),
        "files": uploaded_files,
    }
    summary_path = f"{prefix}/{timestamp}/_summary.json" if prefix else f"{timestamp}/_summary.json"
    blob = bucket.blob(summary_path)
    blob.upload_from_string(
        json.dumps(summary, indent=2),
        content_type="application/json",
    )
    logger.info(f"Uploaded summary: {summary_path}")

    return uploaded_files


def main():
    parser = argparse.ArgumentParser(
        description="Scrape a subreddit and upload results to GCS",
    )
    parser.add_argument(
        "--subreddit-url",
        default=os.environ.get("SUBREDDIT_URL", "https://www.reddit.com/r/AgentsOfAI/new/"),
        help="Full URL of the subreddit to scrape (default: r/AgentsOfAI)",
    )
    parser.add_argument(
        "--gcs-output-path",
        default=os.environ.get("GCS_OUTPUT_PATH"),
        help="GCS path for output, e.g. gs://my-bucket/reddit-data/",
    )
    parser.add_argument(
        "--credentials",
        default=None,
        help="Path to GCP service account JSON key file",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Local directory for output (alternative to GCS)",
    )

    args = parser.parse_args()

    # Set up credentials if provided
    if args.credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.credentials
        logger.info(f"Using credentials: {args.credentials}")

    if not args.gcs_output_path and not args.output_dir:
        logger.error("Either --gcs-output-path or --output-dir is required")
        sys.exit(1)

    logger.info(f"Scraping: {args.subreddit_url}")

    # Run the spider
    from scrapling.spiders import RedditSpider

    spider = RedditSpider(subreddit_url=args.subreddit_url)
    result = spider.start()

    logger.info(f"Scraped {len(result.items)} posts")

    if not result.items:
        logger.warning("No posts found")
        sys.exit(0)

    # Output to GCS or local filesystem
    if args.gcs_output_path:
        logger.info(f"Uploading to GCS: {args.gcs_output_path}")
        uploaded = upload_to_gcs(result.items, args.gcs_output_path)
        logger.info(f"Done! Uploaded {len(uploaded)} files")
    elif args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        for item in result.items:
            post_id = item.get("post_id", "unknown")
            filepath = os.path.join(args.output_dir, f"post_{post_id}.json")
            with open(filepath, "w") as f:
                json.dump(item, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {filepath}")
        logger.info(f"Done! Saved {len(result.items)} posts to {args.output_dir}")


if __name__ == "__main__":
    main()
