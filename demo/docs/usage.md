# Acme Client

## Quick start

Create a client and fetch a user:

```python
client = make_client(api_key="...")
user = client.fetch_user(42)
```

## Configuration

Set `ACME_API_KEY` in your environment, or pass `--timeout` on the command line.
The default retry count is controlled by `MAX_RETRIES`.

## Retries

Failed calls are retried by `retry_call`, which backs off exponentially.

## Changelog

Nothing to see here.
