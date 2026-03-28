# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Does

Deploys [LibreChat](https://github.com/danny-avila/LibreChat) on AWS using Python CDK. LibreChat is configured to use AWS Bedrock (Claude Sonnet 3.5 v2) as its AI backend. All CDK code lives in `cdk/`.

## Development Setup

```bash
cd cdk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Common Commands

All commands run from inside `cdk/` with the venv activated.

```bash
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_app_stack.py -v

# Synthesize CloudFormation templates (dry run, no AWS calls)
cdk synth --context region=ap-southeast-2

# Deploy all stacks
cdk deploy --all --require-approval never --context region=ap-southeast-2

# Deploy a single stack
cdk deploy LibreChatApp --require-approval never --context region=ap-southeast-2
```

AWS profile: `nz-sandbox-ct-genai` (set as `[default]` in `~/.aws/credentials`). Region: `ap-southeast-2`.

## Architecture

Three CDK stacks with strict dependency order:

```
NetworkStack → DatabaseStack → AppStack
```

**NetworkStack** — VPC with 2 AZs, 2 NAT gateways, 3 security groups (ALB → ECS → DocumentDB). Exposes `vpc`, `alb_security_group`, `ecs_security_group`, `db_security_group` as cross-stack references.

**DatabaseStack** — DocumentDB 5.0 cluster (single `memory5.large` instance, TLS disabled, `DESTROY` removal policy). Master credentials stored in Secrets Manager. The password excludes all URI-special characters to avoid MONGO_URI encoding issues.

**AppStack** — Builds a Docker image from `cdk/Dockerfile` (bakes `librechat.yaml` into the official LibreChat image) as a Linux AMD64 asset pushed to ECR. Runs as ECS Fargate (1 vCPU / 2GB) behind an internet-facing ALB on port 80 → container port 3080.

The MONGO_URI is assembled at container startup via a shell entrypoint that URL-encodes the password from Secrets Manager before constructing the URI:
```
mongodb://USER:URL_ENCODED_PASS@HOST:27017/librechat?replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false&authSource=admin
```

Several non-obvious requirements for this URI:
- **`entry_point` + `command` must both be overridden** in the CDK container definition. The LibreChat image has a Docker ENTRYPOINT, so overriding only `command` is silently ignored and the app starts without `MONGO_URI` set.
- **URL-encode the password** using `node -e "process.stdout.write(encodeURIComponent(process.env.DOCDB_PASSWORD))"` — Secrets Manager generates passwords with characters that break URI parsing. Note: `encodeURIComponent` does NOT encode `~`, which itself causes `"Password contains unescaped characters"` in the MongoDB driver. The `exclude_characters` in `DatabaseStack` is deliberately broad to prevent this. If authentication fails after a fresh deployment, verify the generated password contains no characters outside `[A-Za-z0-9]`.
- **`authSource=admin`** is required — DocumentDB always authenticates against the `admin` database regardless of the database name in the URI path. Without it, authentication fails with "Unsupported mechanism [-301]".
- **`retryWrites=false`** is required — DocumentDB does not support MongoDB retryable writes.
- **`replicaSet=rs0`** is required when connecting to the cluster endpoint.

If the DocumentDB master password ever drifts out of sync with the Secrets Manager secret (e.g. after manual intervention), reset both together:
```bash
aws docdb modify-db-cluster --db-cluster-identifier CLUSTER_ID \
  --master-user-password NEW_PASSWORD --apply-immediately --region ap-southeast-2
aws secretsmanager update-secret --secret-id SECRET_ARN \
  --secret-string '{"username":"librechat","password":"NEW_PASSWORD"}' --region ap-southeast-2
```

The ECS task role has `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for all foundation models and inference profiles (`arn:aws:bedrock:*::foundation-model/*` and `arn:aws:bedrock:*:*:inference-profile/*`) — no static AWS credentials needed in the container. The container requires both `AWS_REGION=ap-southeast-2` and `BEDROCK_AWS_DEFAULT_REGION=ap-southeast-2` as environment variables. `AWS_REGION` is for the AWS SDK; `BEDROCK_AWS_DEFAULT_REGION` is specifically required by LibreChat's Bedrock integration to resolve the endpoint and show Bedrock as an available endpoint in the UI.

### Bedrock Model and Inference Profiles

Newer Anthropic models in `ap-southeast-2` (Claude 3.5 Sonnet v2, Claude 4.x) **cannot be invoked directly with on-demand throughput**. They require cross-region inference profiles. Use the APAC inference profile ID (e.g. `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`) instead of the raw model ID (`anthropic.claude-3-5-sonnet-20241022-v2:0`). List available profiles with:
```bash
aws bedrock list-inference-profiles --region ap-southeast-2 --query "inferenceProfileSummaries[*].{id:inferenceProfileId,name:inferenceProfileName}" --output table
```

### Prompt Caching

LibreChat v0.8.1+ enables **prompt caching by default** for all Bedrock Claude models (added in PR #8271). Claude 3.5 Sonnet v2 prompt caching on Bedrock is **preview-only** — unless your account was enrolled in the preview, Bedrock rejects the `cache_control` directives with: `"You invoked an unsupported model or your request did not allow prompt caching."`.

The `promptCache` setting is **not valid at the `endpoints.bedrock` level** — LibreChat's config parser silently strips it. It must be set inside `modelSpecs.list[].preset`:
```yaml
modelSpecs:
  enforce: true
  prioritize: true
  list:
    - name: "claude-3-5-sonnet-v2"
      label: "Claude 3.5 Sonnet v2"
      default: true
      preset:
        endpoint: "bedrock"
        model: "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
        promptCache: false
```
`enforce: true` ensures all requests go through this spec; `prioritize: true` makes model specs take precedence over endpoint defaults. Without this, LibreChat defaults to the Agents endpoint in the UI, which triggers `"agent_id is required in request body"` errors.

## Key Configuration Files

**`cdk/librechat.yaml`** — Baked into the Docker image at `/app/librechat.yaml`. Configures the Bedrock endpoint and available models. Any change here requires rebuilding and redeploying the Docker image.

**`cdk/Dockerfile`** — Extends `ghcr.io/danny-avila/librechat:latest`. Only copies `librechat.yaml` into the image.

## Testing Approach

Tests use `aws_cdk.assertions.Template` to synthesize CDK stacks to CloudFormation in-memory and assert resource properties — no AWS account needed. The CDK method is `resource_count_is()` (not `has_resource_count()`).

The `test_app_stack.py` fixture applies `cdk.Tags.of(app).add("created-by", "etoews")` to mirror `app.py` behaviour, required for the tag propagation assertion.

## Known Production TODOs

- DocumentDB TLS is disabled; enable and add CA cert bundle for production
- `removal_policy=DESTROY` and `deletion_protection=False` on DocumentDB — change for production
- ALB is HTTP only; add ACM certificate + HTTPS listener for production
- Enable prompt caching once the account is enrolled in the Bedrock preview (or switch to a model where prompt caching is GA, such as Claude 3.7 Sonnet or Claude 4.x)
