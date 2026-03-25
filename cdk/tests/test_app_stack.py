import aws_cdk as cdk
from aws_cdk import aws_docdb as docdb
from aws_cdk.assertions import Template, Match
from stacks.network_stack import NetworkStack
from stacks.database_stack import DatabaseStack
from stacks.app_stack import AppStack


def _template():
    app = cdk.App()
    network = NetworkStack(app, "Net")
    database = DatabaseStack(app, "DB", vpc=network.vpc, db_security_group=network.db_security_group)
    stack = AppStack(
        app, "TestApp",
        vpc=network.vpc,
        alb_security_group=network.alb_security_group,
        ecs_security_group=network.ecs_security_group,
        docdb_cluster=database.cluster,
        docdb_secret=database.credentials_secret,
    )
    cdk.Tags.of(app).add("created-by", "etoews")
    return Template.from_stack(stack)


def test_ecs_cluster_exists():
    _template().resource_count_is("AWS::ECS::Cluster", 1)


def test_task_definition_is_fargate():
    _template().has_resource_properties("AWS::ECS::TaskDefinition", {
        "RequiresCompatibilities": ["FARGATE"],
        "NetworkMode": "awsvpc",
    })


def test_alb_exists():
    _template().has_resource_properties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
        "Scheme": "internet-facing",
    })


def test_alb_listener_port_80():
    _template().has_resource_properties("AWS::ElasticLoadBalancingV2::Listener", {
        "Port": 80,
        "Protocol": "HTTP",
    })


def test_task_role_has_bedrock_policy():
    _template().has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": Match.array_with([
                Match.object_like({
                    "Action": Match.array_with(["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]),
                    "Effect": "Allow",
                }),
            ]),
        },
    })


def test_librechat_secrets_exist():
    # JWT + encryption secrets: jwt_secret, jwt_refresh_secret, creds_key, creds_iv
    _template().resource_count_is("AWS::SecretsManager::Secret", 4)


def test_created_by_tag():
    # Tags applied at App level propagate to all resources in every stack
    # Spot-check the ECS cluster
    _template().has_resource_properties("AWS::ECS::Cluster", {
        "Tags": Match.array_with([{"Key": "created-by", "Value": "etoews"}]),
    })
