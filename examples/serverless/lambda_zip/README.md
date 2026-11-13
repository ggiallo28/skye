# lambda_zip

What you learn: a complete AWS Lambda function with Skye, packaged as a plain zip, with no container and no layer.

1. `handler.py`: the function; it creates a Bedrock client once, at cold start, and answers `{"prompt": "..."}`

Build: `sh examples/serverless/lambda_zip/build.sh` (needs `python3` with `pip`, and `zip`; set `PYTHON` to use another interpreter). It installs `skyeai` into `build/`, adds
`handler.py` and writes `function.zip`.

What you get: a zip of **0.61 MB** (1.87 MB unzipped), measured with skyeai 0.3.0. AWS allows 50 MB zipped
and 250 MB unzipped. The CI builds the same zip and fails above `[lambda] max_zip_mb` of `budgets.toml`.

Deploy (Python 3.11 or later; the role needs `bedrock:InvokeModel`):

```bash
aws lambda create-function --function-name skye-hello \
  --runtime python3.12 --handler handler.handler --zip-file fileb://function.zip \
  --role arn:aws:iam::<account>:role/<role-with-bedrock> --timeout 30
aws lambda invoke --function-name skye-hello --cli-binary-format raw-in-base64-out \
  --payload '{"prompt": "Say hello in one word"}' out.json && cat out.json
```

Run locally: `python examples/serverless/lambda_zip/handler.py` with AWS credentials and `AWS_REGION` set.

What you need: `pip install skyeai`; AWS credentials with access to a Bedrock model.
