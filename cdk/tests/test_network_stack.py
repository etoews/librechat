import pytest
import aws_cdk as cdk
from aws_cdk.assertions import Template, Match
from stacks.network_stack import NetworkStack


@pytest.fixture(scope="module")
def template():
    app = cdk.App()
    stack = NetworkStack(app, "TestNetwork")
    return Template.from_stack(stack)


def test_vpc_exists(template):
    template.resource_count_is("AWS::EC2::VPC", 1)


def test_two_nat_gateways(template):
    # One NAT per AZ (2 AZs)
    template.resource_count_is("AWS::EC2::NatGateway", 2)


def test_alb_security_group(template):
    template.has_resource_properties("AWS::EC2::SecurityGroup", {
        "GroupDescription": Match.string_like_regexp("ALB"),
    })


def test_ecs_security_group(template):
    template.has_resource_properties("AWS::EC2::SecurityGroup", {
        "GroupDescription": Match.string_like_regexp("ECS"),
    })


def test_db_security_group(template):
    template.has_resource_properties("AWS::EC2::SecurityGroup", {
        "GroupDescription": Match.string_like_regexp("DocumentDB"),
    })
