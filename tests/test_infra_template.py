from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml


def test_sam_template_defines_serverless_demo_stack() -> None:
    template = _load_template()

    assert template["Transform"] == "AWS::Serverless-2016-10-31"
    resources: dict[str, dict[str, Any]] = template["Resources"]
    resource_types = {name: resource["Type"] for name, resource in resources.items()}
    assert resource_types["MusicRecommenderHttpApi"] == "AWS::Serverless::HttpApi"
    assert resource_types["MusicRecommenderApiFunction"] == "AWS::Serverless::Function"
    assert resource_types["MusicRecommenderUsersTable"] == "AWS::DynamoDB::Table"
    assert resource_types["MusicRecommenderSessionsTable"] == "AWS::DynamoDB::Table"
    assert resource_types["MusicRecommenderFeedbackTable"] == "AWS::DynamoDB::Table"
    assert resource_types["MusicRecommenderPlaylistsTable"] == "AWS::DynamoDB::Table"

    function = resources["MusicRecommenderApiFunction"]["Properties"]
    assert function["CodeUri"] == "../.lambda-build/api"
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
    assert env["RUNTIME_STORE_BACKEND"] == "dynamodb"
    assert "PLAYLISTS_TABLE_NAME" in env
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
    assert "PlaylistsTableName" in outputs


def test_sam_template_schedules_profile_sync_with_least_privilege() -> None:
    template = _load_template()
    resources = template["Resources"]
    parameters = template["Parameters"]
    outputs = template["Outputs"]

    assert parameters["ProfileSyncScheduleExpression"]["Default"] == "cron(0 10 * * ? *)"

    function = resources["MusicRecommenderProfileSyncFunction"]
    properties = function["Properties"]
    assert properties["CodeUri"] == "../.lambda-build/profile-sync"
    assert properties["Handler"] == "music_recommender.api.scheduled_profile_handler.handler"
    assert properties["Timeout"] == 90
    assert properties["Environment"]["Variables"]["RUNTIME_STORE_BACKEND"] == "dynamodb"
    assert properties["Environment"]["Variables"]["USERS_TABLE_NAME"] == {
        "Ref": "MusicRecommenderUsersTable"
    }
    assert properties["Events"]["DailyProfileSync"] == {
        "Type": "Schedule",
        "Properties": {
            "Description": "Refresh the configured Spotify profile cache every day.",
            "Enabled": True,
            "Schedule": {"Ref": "ProfileSyncScheduleExpression"},
        },
    }

    policy_text = json.dumps(properties["Policies"])
    assert "dynamodb:GetItem" in policy_text
    assert "dynamodb:PutItem" in policy_text
    assert "MusicRecommenderUsersTable" in policy_text
    assert "MusicRecommenderSessionsTable" not in policy_text
    assert "MusicRecommenderFeedbackTable" not in policy_text
    assert "MusicRecommenderPlaylistsTable" not in policy_text
    assert "s3:" not in policy_text

    assert outputs["ProfileSyncFunctionName"]["Value"] == {
        "Ref": "MusicRecommenderProfileSyncFunction"
    }


def test_sam_template_enables_operational_logs_alarms_and_table_recovery() -> None:
    template = _load_template()
    resources = template["Resources"]

    http_api = resources["MusicRecommenderHttpApi"]["Properties"]
    access_logs = http_api["AccessLogSettings"]
    assert access_logs["DestinationArn"] == {
        "Fn::GetAtt": ["MusicRecommenderHttpApiAccessLogGroup", "Arn"]
    }
    assert "authorization" not in access_logs["Format"].lower()
    assert "x-api-key" not in access_logs["Format"].lower()
    assert resources["MusicRecommenderHttpApiAccessLogGroup"]["Properties"]["RetentionInDays"] == 14
    assert resources["MusicRecommenderProfileSyncLogGroup"]["Properties"]["RetentionInDays"] == 14

    for table_name in (
        "MusicRecommenderUsersTable",
        "MusicRecommenderSessionsTable",
        "MusicRecommenderFeedbackTable",
        "MusicRecommenderPlaylistsTable",
    ):
        table = resources[table_name]
        assert table["DeletionPolicy"] == "Retain"
        assert table["UpdateReplacePolicy"] == "Retain"
        assert table["Properties"]["PointInTimeRecoverySpecification"] == {
            "PointInTimeRecoveryEnabled": True
        }
        assert table["Properties"]["SSESpecification"] == {"SSEEnabled": True}

    for alarm_name, function_name in (
        ("MusicRecommenderApiErrorsAlarm", "MusicRecommenderApiFunction"),
        ("MusicRecommenderProfileSyncErrorsAlarm", "MusicRecommenderProfileSyncFunction"),
    ):
        alarm = resources[alarm_name]["Properties"]
        assert alarm["Namespace"] == "AWS/Lambda"
        assert alarm["MetricName"] == "Errors"
        assert alarm["Threshold"] == 0
        assert alarm["TreatMissingData"] == "notBreaching"
        assert alarm["Dimensions"] == [{"Name": "FunctionName", "Value": {"Ref": function_name}}]


def _load_template() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(Path("infra/template.yaml").read_text()))
