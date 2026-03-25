import aws_cdk as cdk
from stacks.network_stack import NetworkStack
from stacks.database_stack import DatabaseStack
from stacks.app_stack import AppStack

app = cdk.App()

region = app.node.try_get_context("region") or "us-east-1"
account = app.node.try_get_context("account") or app.account
env = cdk.Environment(account=account, region=region)

network = NetworkStack(app, "LibreChatNetwork", env=env)
database = DatabaseStack(
    app, "LibreChatDatabase",
    vpc=network.vpc,
    db_security_group=network.db_security_group,
    env=env,
)
AppStack(
    app, "LibreChatApp",
    vpc=network.vpc,
    alb_security_group=network.alb_security_group,
    ecs_security_group=network.ecs_security_group,
    docdb_cluster=database.cluster,
    docdb_secret=database.credentials_secret,
    env=env,
)

# Tag all resources across all stacks
cdk.Tags.of(app).add("created-by", "etoews")

app.synth()
