# Traffic generator

Tools for generating sample traffic so you can test how **InstantEvidence** responds to real-world activity.

## What's included

| Folder | Purpose |
|--------|---------|
| `colab/` | S3 object traffic from Google Colab (recommended for AWS bucket demos) |
| `claude/` | Traffic generation via the Claude API |

## S3 traffic in Google Colab

Best for demos and integration checks against a live S3 bucket wired to InstantEvidence.

1. Open [`colab/s3_traffic_generator_mcp_colab.ipynb`](colab/s3_traffic_generator_mcp_colab.ipynb) in [Google Colab](https://colab.research.google.com/).
2. In Colab **Secrets**, add `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. Optionally set `AWS_REGION` (default `us-east-1`).
3. Set **BUCKET** to your InstantEvidence-monitored bucket, then **Runtime → Run all**.

The notebook is self-contained—`colab/` contains only this `.ipynb`; nothing else to download or upload.

## License

MIT
