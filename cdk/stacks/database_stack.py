from aws_cdk import Stack, RemovalPolicy
from aws_cdk import aws_docdb as docdb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class DatabaseStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        db_security_group: ec2.SecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.credentials_secret = secretsmanager.Secret(
            self, "DocDbCredentials",
            description="LibreChat DocumentDB master credentials",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "librechat"}',
                generate_string_key="password",
                exclude_characters='"@/\\:,',
                password_length=32,
            ),
        )

        # Disable TLS for internal VPC communication (enable for production)
        param_group = docdb.ClusterParameterGroup(
            self, "ParamGroup",
            family="docdb5.0",
            description="LibreChat DocumentDB - TLS disabled",
            parameters={"tls": "disabled"},
        )

        self.cluster = docdb.DatabaseCluster(
            self, "Cluster",
            master_user=docdb.Login(
                username="librechat",
                password=self.credentials_secret.secret_value_from_json("password"),
            ),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.MEMORY5, ec2.InstanceSize.LARGE),
            instances=1,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=db_security_group,
            parameter_group=param_group,
            engine_version="5.0.0",
            removal_policy=RemovalPolicy.DESTROY,  # Change to RETAIN for production
            deletion_protection=False,             # Enable for production
        )
