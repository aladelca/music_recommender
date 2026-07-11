from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml


def test_bootstrap_defines_github_oidc_scoped_roles_and_private_artifact_bucket() -> None:
    template = cast(
        dict[str, Any],
        yaml.safe_load(Path("infra/deployment-role-template.yaml").read_text()),
    )
    resources = template["Resources"]

    provider = resources["GitHubActionsOidcProvider"]
    assert provider["Type"] == "AWS::IAM::OIDCProvider"
    assert provider["Properties"]["Url"] == "https://token.actions.githubusercontent.com"
    assert provider["Properties"]["ClientIdList"] == ["sts.amazonaws.com"]

    bucket = resources["SamArtifactBucket"]["Properties"]
    assert bucket["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert bucket["BucketEncryption"]

    deployment_role = resources["DeploymentRole"]["Properties"]
    assert deployment_role["MaxSessionDuration"] == 14_400
    trust = json.dumps(deployment_role["AssumeRolePolicyDocument"])
    assert "repo:${GitHubOrg}/${GitHubRepo}:environment:production" in trust
    assert "token.actions.githubusercontent.com:aud" in trust
    policy = json.dumps(deployment_role["Policies"])
    assert "cloudformation:" in policy
    assert "secretsmanager:GetSecretValue" in policy
    assert "secretsmanager:PutSecretValue" in policy
    assert "iam:PassRole" in policy
    assert '"Action": "*"' not in policy
    assert "AdministratorAccess" not in policy

    execution_role = resources["CloudFormationExecutionRole"]["Properties"]
    assert "cloudformation.amazonaws.com" in json.dumps(execution_role["AssumeRolePolicyDocument"])
    assert "iam:CreateRole" in json.dumps(execution_role["Policies"])
    assert "transform/Serverless-2016-10-31" in json.dumps(execution_role["Policies"])


def test_deploy_script_and_workflow_require_scoped_artifact_and_execution_roles() -> None:
    script = Path("scripts/deploy_api_sam.sh").read_text()
    workflow = Path(".github/workflows/deploy-aws.yml").read_text()

    assert "SAM_ARTIFACT_BUCKET" in script
    assert "CLOUDFORMATION_EXECUTION_ROLE_ARN" in script
    assert '--s3-bucket "$SAM_ARTIFACT_BUCKET"' in script
    assert '--role-arn "$CLOUDFORMATION_EXECUTION_ROLE_ARN"' in script
    assert "--resolve-s3" not in script
    assert "SAM_ARTIFACT_BUCKET: ${{ vars.AWS_SAM_ARTIFACT_BUCKET }}" in workflow
    assert (
        "CLOUDFORMATION_EXECUTION_ROLE_ARN: ${{ vars.AWS_CLOUDFORMATION_EXECUTION_ROLE_ARN }}"
    ) in workflow
