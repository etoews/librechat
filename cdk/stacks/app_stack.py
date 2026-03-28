import os
from aws_cdk import Stack, Duration, CfnOutput
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_docdb as docdb
from constructs import Construct


class AppStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        alb_security_group: ec2.SecurityGroup,
        ecs_security_group: ec2.SecurityGroup,
        docdb_cluster: docdb.DatabaseCluster,
        docdb_secret: secretsmanager.Secret,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Secrets ---
        jwt_secret = secretsmanager.Secret(
            self, "JwtSecret",
            description="LibreChat JWT_SECRET",
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=64, exclude_punctuation=True),
        )
        jwt_refresh_secret = secretsmanager.Secret(
            self, "JwtRefreshSecret",
            description="LibreChat JWT_REFRESH_SECRET",
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=64, exclude_punctuation=True),
        )
        creds_key = secretsmanager.Secret(
            self, "CredsKey",
            description="LibreChat CREDS_KEY (32-byte hex)",
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=32, exclude_punctuation=True),
        )
        creds_iv = secretsmanager.Secret(
            self, "CredsIv",
            description="LibreChat CREDS_IV (16-byte hex)",
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=16, exclude_punctuation=True),
        )

        # --- IAM ---
        execution_role = iam.Role(
            self, "ExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")],
        )
        # Allow execution role to read secrets
        for secret in [docdb_secret, jwt_secret, jwt_refresh_secret, creds_key, creds_iv]:
            secret.grant_read(execution_role)

        task_role = iam.Role(
            self, "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        task_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                "arn:aws:bedrock:*::foundation-model/*",
                "arn:aws:bedrock:*:*:inference-profile/*",
            ],
        ))

        # --- Docker Image ---
        image_asset = ecr_assets.DockerImageAsset(
            self, "LibreChatImage",
            directory=os.path.join(os.path.dirname(__file__), ".."),  # cdk/ dir has Dockerfile
            platform=ecr_assets.Platform.LINUX_AMD64,
        )

        # --- ECS Cluster ---
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, enable_fargate_capacity_providers=True)

        log_group = logs.LogGroup(self, "LogGroup", retention=logs.RetentionDays.ONE_WEEK)

        # --- Task Definition ---
        task_def = ecs.FargateTaskDefinition(
            self, "TaskDef",
            cpu=1024,
            memory_limit_mib=2048,
            execution_role=execution_role,
            task_role=task_role,
        )

        # Build MONGO_URI from DocumentDB cluster endpoint + credentials secret
        # Format: mongodb://user:pass@host:27017/librechat?replicaSet=rs0&...
        mongo_uri_suffix = (
            f"@{docdb_cluster.cluster_endpoint.hostname}:27017"
            "/librechat?replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false&authSource=admin"
        )

        task_def.add_container(
            "LibreChat",
            image=ecs.ContainerImage.from_docker_image_asset(image_asset),
            # Override entrypoint to assemble MONGO_URI from individual secret env vars
            # before handing off to the app's npm start script
            entry_point=["/bin/sh", "-c"],
            command=[
                'export ENCODED_PASSWORD=$(node -e "process.stdout.write(encodeURIComponent(process.env.DOCDB_PASSWORD))") && '
                'export MONGO_URI="mongodb://${DOCDB_USERNAME}:${ENCODED_PASSWORD}${MONGO_URI_SUFFIX}" && '
                'npm run backend'
            ],
            environment={
                "NODE_ENV": "production",
                "HOST": "0.0.0.0",
                "PORT": "3080",
                "MONGO_URI_SUFFIX": mongo_uri_suffix,
                "ALLOW_REGISTRATION": "false",
                "AWS_REGION": "ap-southeast-2",
                "BEDROCK_AWS_DEFAULT_REGION": "ap-southeast-2",
            },
            secrets={
                "DOCDB_USERNAME": ecs.Secret.from_secrets_manager(docdb_secret, "username"),
                "DOCDB_PASSWORD": ecs.Secret.from_secrets_manager(docdb_secret, "password"),
                "JWT_SECRET": ecs.Secret.from_secrets_manager(jwt_secret),
                "JWT_REFRESH_SECRET": ecs.Secret.from_secrets_manager(jwt_refresh_secret),
                "CREDS_KEY": ecs.Secret.from_secrets_manager(creds_key),
                "CREDS_IV": ecs.Secret.from_secrets_manager(creds_iv),
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="librechat", log_group=log_group),
            port_mappings=[ecs.PortMapping(container_port=3080)],
        )

        # --- ALB ---
        alb = elbv2.ApplicationLoadBalancer(
            self, "Alb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_security_group,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        listener = alb.add_listener("HttpListener", port=80, open=False)

        # --- ECS Service ---
        service = ecs.FargateService(
            self, "Service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            security_groups=[ecs_security_group],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            assign_public_ip=False,
        )

        listener.add_targets(
            "LibreChatTarget",
            port=3080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(path="/", healthy_http_codes="200-302"),
            deregistration_delay=Duration.seconds(30),
        )

        CfnOutput(self, "LibreChatUrl", value=f"http://{alb.load_balancer_dns_name}", description="LibreChat URL")
