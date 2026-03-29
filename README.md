# LibreChat on AWS

Deploy [LibreChat](https://github.com/danny-avila/LibreChat) on AWS using Python CDK with [AWS Bedrock](https://aws.amazon.com/bedrock/) as the AI backend.

## Architecture

```
Internet → ALB (HTTP:80) → ECS Fargate (LibreChat:3080) → DocumentDB
                                    ↓
                              AWS Bedrock (Claude 3.5 Sonnet v2)
```

Three CDK stacks deployed in order:

| Stack | Resources |
|-------|-----------|
| **NetworkStack** | VPC, 2 AZs, 2 NAT gateways, security groups (ALB → ECS → DocumentDB) |
| **DatabaseStack** | DocumentDB 5.0 cluster, Secrets Manager credentials |
| **AppStack** | ECR image, ECS Fargate service, ALB, IAM roles, Secrets Manager (JWT/encryption keys) |

The ECS task role grants Bedrock invoke permissions — no static AWS credentials in the container. A custom Docker image bakes the `librechat.yaml` Bedrock configuration into the official LibreChat image.

## Prerequisites

- AWS CLI configured with Bedrock model access enabled for Claude 3.5 Sonnet v2
- CDK bootstrapped: `cdk bootstrap aws://ACCOUNT/REGION`
- Docker Desktop running
- Python 3.11+
- Node.js (for CDK CLI: `npm install -g aws-cdk`)

## Quick Start

```bash
cd cdk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Run tests
pytest tests/ -v

# Deploy
cdk deploy --all --require-approval never --context region=ap-southeast-2
```

The deploy outputs a `LibreChatUrl` — open it in your browser to access LibreChat.

## Configuration

**`cdk/librechat.yaml`** configures the Bedrock endpoint and available models. Changes require redeploying to rebuild the Docker image.

**`cdk/app.py`** wires the three stacks together. Pass `--context region=REGION` to deploy to a different region.

## Known Limitations

- DocumentDB TLS is disabled (enable for production)
- ALB is HTTP only (add ACM certificate + HTTPS for production)
- DocumentDB has `DESTROY` removal policy (change to `RETAIN` for production)
- Self-registration is disabled; users must be provisioned manually
