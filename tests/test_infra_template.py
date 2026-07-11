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


def test_sam_template_defines_isolated_multi_user_product_runtime() -> None:
    template = _load_template()
    resources = template["Resources"]
    parameters = template["Parameters"]
    outputs = template["Outputs"]

    assert parameters["ProductAuthMode"]["AllowedValues"] == ["hybrid", "spotify_session"]
    assert parameters["EnableReservedConcurrency"]["Default"] == "false"
    assert parameters["AppBaseUrl"]["AllowedPattern"].startswith("^https://")
    assert parameters["MusicBrainzContactEmail"]["AllowedPattern"]
    assert "[:space:]" not in parameters["MusicBrainzContactEmail"]["AllowedPattern"]
    assert resources["OutsideTheLoopHttpApi"]["Type"] == "AWS::Serverless::HttpApi"
    assert resources["OutsideTheLoopTokenKey"]["Type"] == "AWS::KMS::Key"
    assert resources["OutsideTheLoopTokenKey"]["Properties"]["EnableKeyRotation"] is True
    assert resources["OutsideTheLoopDiscoveryQueue"]["Properties"]["FifoQueue"] is True
    assert resources["OutsideTheLoopDiscoveryDlq"]["Properties"]["FifoQueue"] is True

    api = resources["OutsideTheLoopApiFunction"]["Properties"]
    assert api["CodeUri"] == "../.lambda-build/product-api"
    assert api["Handler"] == "music_recommender.api.product_lambda_handler.handler"
    assert api["ReservedConcurrentExecutions"] == {
        "Fn::If": ["UseProductReservedConcurrency", 5, {"Ref": "AWS::NoValue"}]
    }
    api_env = api["Environment"]["Variables"]
    assert api_env["RUNTIME_STORE_BACKEND"] == "supabase"
    assert api_env["AUTH_MODE"] == {"Ref": "ProductAuthMode"}
    assert api_env["APP_BASE_URL"] == {"Ref": "AppBaseUrl"}
    assert api_env["SPOTIFY_TOKEN_KMS_KEY_ID"] == {"Fn::GetAtt": ["OutsideTheLoopTokenKey", "Arn"]}
    assert api_env["SPOTIFY_PRODUCT_SCOPES"] == (
        "user-read-private playlist-modify-private playlist-modify-public"
    )
    assert api_env["DISCOVERY_QUEUE_URL"] == {"Ref": "OutsideTheLoopDiscoveryQueue"}
    assert "secretsmanager" in str(api_env["SUPABASE_DB_URL"])
    assert "secretsmanager" in str(api_env["SPOTIFY_APP_CLIENT_SECRET"])
    assert "secretsmanager" in str(api_env["OBSERVABILITY_HASH_KEY"])
    assert not any("S3" in key or "BUCKET" in key or "DATA_ROOT" in key for key in api_env)
    api_policy = json.dumps(api["Policies"])
    assert "kms:Decrypt" in api_policy
    assert "kms:Encrypt" in api_policy
    assert "sqs:SendMessage" in api_policy
    assert "s3:" not in api_policy.lower()

    worker = resources["OutsideTheLoopDiscoveryWorkerFunction"]["Properties"]
    assert worker["CodeUri"] == "../.lambda-build/discovery-worker"
    assert worker["Handler"] == "music_recommender.api.discovery_worker_handler.handler"
    assert worker["ReservedConcurrentExecutions"] == {
        "Fn::If": ["UseProductReservedConcurrency", 2, {"Ref": "AWS::NoValue"}]
    }
    assert worker["Events"]["DiscoveryQueue"]["Properties"]["FunctionResponseTypes"] == [
        "ReportBatchItemFailures"
    ]
    assert "MaximumBatchingWindowInSeconds" not in worker["Events"]["DiscoveryQueue"]["Properties"]
    assert "s3:" not in json.dumps(worker.get("Policies", [])).lower()
    assert not any(
        "S3" in key or "BUCKET" in key or "DATA_ROOT" in key
        for key in worker["Environment"]["Variables"]
    )

    cleanup = resources["OutsideTheLoopCleanupFunction"]["Properties"]
    assert cleanup["CodeUri"] == "../.lambda-build/cleanup"
    assert cleanup["Handler"] == "music_recommender.api.cleanup_handler.handler"
    assert cleanup["ReservedConcurrentExecutions"] == {
        "Fn::If": ["UseProductReservedConcurrency", 1, {"Ref": "AWS::NoValue"}]
    }
    assert cleanup["Events"]["DailyCleanup"]["Properties"]["Schedule"] == {
        "Ref": "CleanupScheduleExpression"
    }
    assert "s3:" not in json.dumps(cleanup.get("Policies", [])).lower()

    assert outputs["ProductApiUrl"]["Value"] == {
        "Fn::Sub": (
            "https://${OutsideTheLoopHttpApi}.execute-api.${AWS::Region}.${AWS::URLSuffix}/"
        )
    }
    assert outputs["DiscoveryDlqUrl"]["Value"] == {"Ref": "OutsideTheLoopDiscoveryDlq"}


def test_product_runtime_has_queue_database_and_lambda_alarms_without_sensitive_logs() -> None:
    template = _load_template()
    resources = template["Resources"]
    access_log = resources["OutsideTheLoopHttpApi"]["Properties"]["AccessLogSettings"]

    assert "authorization" not in access_log["Format"].lower()
    assert "cookie" not in access_log["Format"].lower()
    assert "querystring" not in access_log["Format"].lower()
    for alarm_name in (
        "OutsideTheLoopApiErrorsAlarm",
        "OutsideTheLoopApiDurationAlarm",
        "OutsideTheLoopWorkerErrorsAlarm",
        "OutsideTheLoopCleanupErrorsAlarm",
        "OutsideTheLoopDiscoveryDlqAlarm",
        "OutsideTheLoopDatabaseFailureAlarm",
        "OutsideTheLoopSourceFailureAlarm",
        "OutsideTheLoopSpotifyReconnectAlarm",
    ):
        assert resources[alarm_name]["Type"] == "AWS::CloudWatch::Alarm"

    assert resources["OutsideTheLoopDatabaseFailureAlarm"]["Properties"]["Namespace"] == (
        "OutsideTheLoop/Product"
    )
    assert resources["OutsideTheLoopAlarmTopic"]["Type"] == "AWS::SNS::Topic"
    assert resources["OutsideTheLoopAlarmSubscription"]["Properties"]["Endpoint"] == {
        "Ref": "MusicBrainzContactEmail"
    }
    alarm_action = {"Ref": "OutsideTheLoopAlarmTopic"}
    for alarm_name in (
        "OutsideTheLoopApiErrorsAlarm",
        "OutsideTheLoopApiDurationAlarm",
        "OutsideTheLoopWorkerErrorsAlarm",
        "OutsideTheLoopCleanupErrorsAlarm",
        "OutsideTheLoopDiscoveryDlqAlarm",
        "OutsideTheLoopDiscoveryAgeAlarm",
        "OutsideTheLoopApiResponseErrorsAlarm",
        "OutsideTheLoopDatabaseFailureAlarm",
        "OutsideTheLoopSourceFailureAlarm",
        "OutsideTheLoopSpotifyReconnectAlarm",
    ):
        assert alarm_action in resources[alarm_name]["Properties"]["AlarmActions"]


def _load_template() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(Path("infra/template.yaml").read_text()))
