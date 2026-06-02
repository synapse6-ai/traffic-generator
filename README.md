# S3 upload and PII check (Colab)

Use this repo’s **Google Colab notebook** to upload files from your computer into an **S3 bucket** monitored by **InstantEvidence** (GuardrailStudio), then see **PII vs non-PII** classification through the product’s MCP tools.

No synthetic traffic generator and no AWS CLI required for the demo flow.

## Who this is for

- Engineers or solutions folks **testing InstantEvidence** against a real bucket  
- Anyone who needs a **repeatable upload + PII check** without writing custom scripts  

## What happens end-to-end

1. You add **Colab secrets** (AWS keys + InstantEvidence MCP URL and API key).  
2. You **pick files** on your laptop; Colab holds them temporarily.  
3. The notebook **uploads** them to your S3 bucket under a prefix (e.g. `uploads/`).  
4. You **list** the bucket to confirm objects exist in AWS.  
5. You query **InstantEvidence** for PII status and governed inventory (may take a few minutes after upload).  

## Quick start (Colab)

1. Open **[`colab/s3_upload_and_classify.ipynb`](colab/s3_upload_and_classify.ipynb)** in [Google Colab](https://colab.research.google.com/) (best: **File → Open notebook → GitHub** and select this repo).  
2. In Colab, open **Secrets** (key icon) and add:

   | Secret | Notes |
   |--------|--------|
   | `AWS_ACCESS_KEY_ID` | IAM user limited to your test bucket |
   | `AWS_SECRET_ACCESS_KEY` | Matching secret |
   | `AWS_REGION` | Optional; defaults to `us-east-1` |
   | `GUARDRAILSTUDIO_MCP_URL` | From InstantEvidence **Settings → MCP** (must end with `/v1/mcp`) |
   | `GUARDRAILSTUDIO_MCP_TOKEN` | `gks_live_…` from **Settings → API keys** |

3. In the notebook, set **BUCKET** to the same bucket InstantEvidence monitors.  
4. **Runtime → Run all**, or follow the numbered steps in the notebook.  

The notebook includes step-by-step explanations, expected output, and a troubleshooting table.

## Repo layout

| Path | Purpose |
|------|---------|
| [`colab/s3_upload_and_classify.ipynb`](colab/s3_upload_and_classify.ipynb) | User-facing runbook (start here) |
| [`colab/colab_bootstrap.py`](colab/colab_bootstrap.py) | Loads helpers; reuses MCP connections |
| [`colab/aws_credentials.py`](colab/aws_credentials.py) | AWS secrets / env |
| [`colab/mcp_s3_client.py`](colab/mcp_s3_client.py) | S3 via AWS API MCP |
| [`colab/guardrail_mcp_client.py`](colab/guardrail_mcp_client.py) | InstantEvidence MCP |

## Advanced

- **Test a Git branch:** in Colab, set `COLAB_HELPERS_RAW_BASE` to  
  `https://raw.githubusercontent.com/synapse6-ai/traffic-generator/<branch>/colab`
- **Developers:** `cd colab && python -m pytest tests/ -q`

## License

MIT
