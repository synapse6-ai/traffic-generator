# traffic-generator

A traffic generator for testing AI guardrails, with implementations for two execution environments.

## Structure

- `colab/` — Google Colab S3 traffic generator via AWS MCP (`awslabs.aws-api-mcp-server`)
- `claude/` — Claude API-based traffic generator

## Colab (S3 via MCP)

1. Open `colab/s3_traffic_generator_mcp_colab.ipynb` in Google Colab.
2. Set Colab secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_REGION`.
3. Run all cells. Upload the three helper `.py` files if prompted.

Tests:

```bash
cd colab && python3 -m pytest tests/ -q
```

## License

MIT
