"""Cloud Run HTTP handler for the Scrapling Reddit Spider.

Accepts HTTP requests with parameters for subreddit URL and GCS output path.
Service account credentials are passed via GOOGLE_APPLICATION_CREDENTIALS env var
or through the request body.

Usage:
    POST / with JSON body:
    {
        "subreddit_url": "https://www.reddit.com/r/AgentsOfAI/new/",
        "gcs_output_path": "gs://my-bucket/reddit-data/",
        "credentials_json": "<optional base64-encoded SA key>"
    }

    GET /health -> 200 OK
"""

import os
import json
import logging
import tempfile
import base64
from datetime import datetime, timezone

from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _setup_credentials(credentials_json: str = None):
    """Set up GCP credentials from base64-encoded JSON or rely on env/metadata."""
    if credentials_json:
        decoded = base64.b64decode(credentials_json)
        cred_path = os.path.join(tempfile.gettempdir(), "sa_credentials.json")
        with open(cred_path, "wb") as f:
            f.write(decoded)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        logger.info("Credentials set from request body")


def _upload_to_gcs(data: list, gcs_output_path: str):
    """Upload scraped data as JSON files to a GCS path.

    Args:
        data: List of scraped post dicts
        gcs_output_path: Full GCS path like gs://bucket/prefix/
    """
    from google.cloud import storage

    # Parse bucket and prefix from gs:// path
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

    # Also upload a manifest/summary file
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

    return uploaded_files


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "scrapling-reddit-spider"}), 200


@app.route("/", methods=["POST"])
def run_spider():
    """Run the Reddit spider and upload results to GCS."""
    try:
        body = request.get_json(force=True, silent=True) or {}

        subreddit_url = body.get(
            "subreddit_url", "https://www.reddit.com/r/AgentsOfAI/new/"
        )
        gcs_output_path = body.get("gcs_output_path")
        credentials_json = body.get("credentials_json")

        if not gcs_output_path:
            # Fall back to env var
            gcs_output_path = os.environ.get("GCS_OUTPUT_PATH")

        if not gcs_output_path:
            return jsonify({"error": "gcs_output_path is required (body or GCS_OUTPUT_PATH env)"}), 400

        # Set up credentials if provided
        _setup_credentials(credentials_json)

        logger.info(f"Starting spider for: {subreddit_url}")
        logger.info(f"Output to: {gcs_output_path}")

        # Import and run the spider
        from scrapling.spiders import RedditSpider

        spider = RedditSpider(subreddit_url=subreddit_url)
        result = spider.start()

        logger.info(f"Scraped {len(result.items)} posts")

        if not result.items:
            return jsonify({
                "status": "completed",
                "posts_scraped": 0,
                "message": "No posts found",
            }), 200

        # Upload to GCS
        uploaded = _upload_to_gcs(result.items, gcs_output_path)

        return jsonify({
            "status": "completed",
            "posts_scraped": len(result.items),
            "gcs_files": uploaded,
            "subreddit_url": subreddit_url,
        }), 200

    except Exception as e:
        logger.exception("Spider execution failed")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
