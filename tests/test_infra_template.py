from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def test_sam_template_defines_serverless_demo_stack() -> None:
    template = yaml.safe_load(Path("infra/template.yaml").read_text())

    assert template["Transform"] == "AWS::Serverless-2016-10-31"
    resources: dict[str, dict[str, Any]] = template["Resources"]
    resource_types = {name: resource["Type"] for name, resource in resources.items()}
    assert resource_types["MusicRecommenderHttpApi"] == "AWS::Serverless::HttpApi"
    assert resource_types["MusicRecommenderApiFunction"] == "AWS::Serverless::Function"
    assert resource_types["MusicRecommenderUsersTable"] == "AWS::DynamoDB::Table"
    assert resource_types["MusicRecommenderSessionsTable"] == "AWS::DynamoDB::Table"
    assert resource_types["MusicRecommenderFeedbackTable"] == "AWS::DynamoDB::Table"

    function = resources["MusicRecommenderApiFunction"]["Properties"]
    assert function["Handler"] == "music_recommender.api.lambda_handler.handler"
    assert function["Runtime"] == "python3.12"
    env = function["Environment"]["Variables"]
    assert env["PYTHONPATH"] == "/var/task/src"
    assert env["RECOMMENDER_DATA_MODE"] == "s3"
    assert "MUSIC_RECOMMENDER_BUCKET" in env
    assert "AWS_SECRETS_PREFIX" in env
    assert "RECOMMENDER_API_KEY" in env
    assert "SPOTIFY_APP_CLIENT_ID" in env
    assert "SPOTIFY_APP_CLIENT_SECRET" in env
    assert "SPOTIFY_USER_REFRESH_TOKEN" in env
    assert "OPENAI_API_KEY" in env
    assert "secretsmanager" in str(env["SPOTIFY_APP_CLIENT_SECRET"])

    policies = function["Policies"]
    policy_text = str(policies)
    assert "dynamodb:GetItem" in policy_text
    assert "dynamodb:PutItem" in policy_text
    assert "s3:GetObject" in policy_text
    assert "secretsmanager:GetSecretValue" in policy_text

    outputs = template["Outputs"]
    assert "ApiUrl" in outputs
    assert "ApiFunctionName" in outputs
