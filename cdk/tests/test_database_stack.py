import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk.assertions import Template, Match
from stacks.network_stack import NetworkStack
from stacks.database_stack import DatabaseStack


def _template():
    app = cdk.App()
    network = NetworkStack(app, "Net")
    stack = DatabaseStack(app, "TestDB", vpc=network.vpc, db_security_group=network.db_security_group)
    return Template.from_stack(stack)


def test_docdb_cluster_exists():
    _template().resource_count_is("AWS::DocDB::DBCluster", 1)


def test_docdb_instance_exists():
    _template().resource_count_is("AWS::DocDB::DBInstance", 1)


def test_tls_disabled_parameter_group():
    _template().has_resource_properties("AWS::DocDB::DBClusterParameterGroup", {
        "Parameters": {"tls": "disabled"},
    })


def test_credentials_secret_exists():
    _template().resource_count_is("AWS::SecretsManager::Secret", 1)


def test_cluster_uses_parameter_group():
    _template().has_resource_properties("AWS::DocDB::DBCluster", {
        "DBClusterParameterGroupName": Match.any_value(),
    })
