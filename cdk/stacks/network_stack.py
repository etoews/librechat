from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self, "Vpc",
            max_azs=2,
            nat_gateways=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="Private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
            ],
        )

        self.alb_security_group = ec2.SecurityGroup(
            self, "AlbSg",
            vpc=self.vpc,
            description="ALB Security Group",
            allow_all_outbound=True,
        )
        self.alb_security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP from internet")

        self.ecs_security_group = ec2.SecurityGroup(
            self, "EcsSg",
            vpc=self.vpc,
            description="ECS Tasks Security Group",
            allow_all_outbound=True,
        )
        self.ecs_security_group.add_ingress_rule(
            self.alb_security_group, ec2.Port.tcp(3080), "LibreChat port from ALB"
        )

        self.db_security_group = ec2.SecurityGroup(
            self, "DbSg",
            vpc=self.vpc,
            description="DocumentDB Security Group",
            allow_all_outbound=False,
        )
        self.db_security_group.add_ingress_rule(
            self.ecs_security_group, ec2.Port.tcp(27017), "MongoDB from ECS"
        )
