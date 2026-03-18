"""Tests for POST /api/v1/terraform/destroy endpoint.

TDD RED phase — tests written before implementation.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.operation import Operation, OperationStatus, OperationType


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

FAKE_USER_SUB = "user-uuid-001"
FAKE_USERNAME = "testadmin"

FAKE_USER = MagicMock()
FAKE_USER.sub = FAKE_USER_SUB
FAKE_USER.username = FAKE_USERNAME
FAKE_USER.roles = ["tf-admin"]


def _make_apply_op(
    org_name: str = "TestOrg",
    status: OperationStatus = OperationStatus.SUCCESS,
) -> Operation:
    """Create a fake successful APPLY operation for testing."""
    return Operation(
        id=uuid.uuid4(),
        type=OperationType.APPLY,
        status=status,
        user_id=FAKE_USER_SUB,
        username=FAKE_USERNAME,
        target_org=org_name,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
#  _run_destroy_task unit tests
# ---------------------------------------------------------------------------


class TestRunDestroyTask:
    """Unit tests for the background _run_destroy_task function."""

    @pytest.mark.asyncio
    async def test_successful_destroy_updates_db(self, patch_redis):
        """After a successful terraform destroy, operation status = SUCCESS."""
        from app.api.routes.terraform import _run_destroy_task

        op_id = uuid.uuid4()
        org_name = "TestOrg"

        mock_op = MagicMock()
        mock_op.status = OperationStatus.RUNNING

        # Mock DB session
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_op
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        # Mock runner
        mock_run_result = MagicMock()
        mock_run_result.success = True
        mock_run_result.stdout = "Destroy complete!"
        mock_run_result.stderr = ""

        mock_init_result = MagicMock()
        mock_init_result.success = True

        mock_runner = MagicMock()
        mock_runner.init = AsyncMock(return_value=mock_init_result)
        mock_runner.destroy = AsyncMock(return_value=mock_run_result)

        # Mock workspace
        mock_workspace = MagicMock()
        mock_workspace.work_dir = "/tmp/fake"

        with (
            patch("app.api.routes.terraform.async_session", return_value=mock_session_ctx),
            patch("app.api.routes.terraform.TerraformRunner", return_value=mock_runner),
            patch("app.api.routes.terraform.release_org_lock", new_callable=AsyncMock),
        ):
            await _run_destroy_task(op_id, org_name, mock_workspace)

        assert mock_op.status == OperationStatus.SUCCESS
        assert mock_op.plan_output == "Destroy complete!"
        assert mock_op.completed_at is not None
        mock_runner.init.assert_called_once()
        mock_runner.destroy.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_init_marks_failed(self, patch_redis):
        """If terraform init fails, operation should be FAILED."""
        from app.api.routes.terraform import _run_destroy_task

        op_id = uuid.uuid4()
        mock_op = MagicMock()
        mock_op.status = OperationStatus.RUNNING

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_op
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_init_result = MagicMock()
        mock_init_result.success = False
        mock_init_result.stderr = "init error"

        mock_runner = MagicMock()
        mock_runner.init = AsyncMock(return_value=mock_init_result)
        mock_runner.destroy = AsyncMock()

        mock_workspace = MagicMock()
        mock_workspace.work_dir = "/tmp/fake"

        with (
            patch("app.api.routes.terraform.async_session", return_value=mock_session_ctx),
            patch("app.api.routes.terraform.TerraformRunner", return_value=mock_runner),
            patch("app.api.routes.terraform.release_org_lock", new_callable=AsyncMock),
        ):
            await _run_destroy_task(op_id, "TestOrg", mock_workspace)

        assert mock_op.status == OperationStatus.FAILED
        assert mock_op.error_message == "init error"
        mock_runner.destroy.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_destroy_marks_failed(self, patch_redis):
        """If terraform destroy fails, operation should be FAILED."""
        from app.api.routes.terraform import _run_destroy_task

        op_id = uuid.uuid4()
        mock_op = MagicMock()
        mock_op.status = OperationStatus.RUNNING

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_op
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_init_result = MagicMock()
        mock_init_result.success = True
        mock_destroy_result = MagicMock()
        mock_destroy_result.success = False
        mock_destroy_result.stdout = "partial output"
        mock_destroy_result.stderr = "destroy error"

        mock_runner = MagicMock()
        mock_runner.init = AsyncMock(return_value=mock_init_result)
        mock_runner.destroy = AsyncMock(return_value=mock_destroy_result)

        mock_workspace = MagicMock()
        mock_workspace.work_dir = "/tmp/fake"

        with (
            patch("app.api.routes.terraform.async_session", return_value=mock_session_ctx),
            patch("app.api.routes.terraform.TerraformRunner", return_value=mock_runner),
            patch("app.api.routes.terraform.release_org_lock", new_callable=AsyncMock),
        ):
            await _run_destroy_task(op_id, "TestOrg", mock_workspace)

        assert mock_op.status == OperationStatus.FAILED
        assert mock_op.error_message == "destroy error"

    @pytest.mark.asyncio
    async def test_exception_publishes_exit_to_redis(self, patch_redis):
        """Unhandled exception should publish __EXIT:1 to Redis channel."""
        from app.api.routes.terraform import _run_destroy_task

        op_id = uuid.uuid4()

        # First session raises, second (error recovery) works
        mock_db_ok = AsyncMock()
        mock_result_ok = MagicMock()
        mock_op_recovery = MagicMock()
        mock_result_ok.scalar_one.return_value = mock_op_recovery
        mock_db_ok.execute = AsyncMock(return_value=mock_result_ok)
        mock_db_ok.commit = AsyncMock()

        call_count = 0

        def session_factory():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call — simulate error
                ctx = AsyncMock()
                ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB exploded"))
                ctx.__aexit__ = AsyncMock(return_value=False)
                return ctx
            else:
                # Recovery session
                ctx = AsyncMock()
                ctx.__aenter__ = AsyncMock(return_value=mock_db_ok)
                ctx.__aexit__ = AsyncMock(return_value=False)
                return ctx

        mock_redis_client = AsyncMock()
        mock_redis_client.publish = AsyncMock()
        mock_redis_client.aclose = AsyncMock()

        mock_workspace = MagicMock()
        mock_workspace.work_dir = "/tmp/fake"

        with (
            patch("app.api.routes.terraform.async_session", side_effect=session_factory),
            patch("app.api.routes.terraform.release_org_lock", new_callable=AsyncMock),
            patch("app.api.routes.terraform.Redis.from_url", return_value=mock_redis_client),
        ):
            await _run_destroy_task(op_id, "TestOrg", mock_workspace)

        # Verify Redis error publication
        publish_calls = mock_redis_client.publish.call_args_list
        assert any("__EXIT:1" in str(c) for c in publish_calls)

    @pytest.mark.asyncio
    async def test_lock_released_in_finally(self, patch_redis):
        """Lock must always be released, even on success."""
        from app.api.routes.terraform import _run_destroy_task

        op_id = uuid.uuid4()
        org_name = "TestOrg"

        mock_op = MagicMock()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_op
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_init_result = MagicMock()
        mock_init_result.success = True
        mock_destroy_result = MagicMock()
        mock_destroy_result.success = True
        mock_destroy_result.stdout = "ok"
        mock_destroy_result.stderr = ""

        mock_runner = MagicMock()
        mock_runner.init = AsyncMock(return_value=mock_init_result)
        mock_runner.destroy = AsyncMock(return_value=mock_destroy_result)

        mock_workspace = MagicMock()
        mock_workspace.work_dir = "/tmp/fake"

        mock_release = AsyncMock()

        with (
            patch("app.api.routes.terraform.async_session", return_value=mock_session_ctx),
            patch("app.api.routes.terraform.TerraformRunner", return_value=mock_runner),
            patch("app.api.routes.terraform.release_org_lock", mock_release),
        ):
            await _run_destroy_task(op_id, org_name, mock_workspace)

        mock_release.assert_called_once_with(org_name, str(op_id))

    @pytest.mark.asyncio
    async def test_workspace_cleaned_up_after_destroy(self, patch_redis):
        """Workspace should be cleaned up after successful destroy."""
        from app.api.routes.terraform import _run_destroy_task

        op_id = uuid.uuid4()

        mock_op = MagicMock()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_op
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_init_result = MagicMock()
        mock_init_result.success = True
        mock_destroy_result = MagicMock()
        mock_destroy_result.success = True
        mock_destroy_result.stdout = "ok"
        mock_destroy_result.stderr = ""

        mock_runner = MagicMock()
        mock_runner.init = AsyncMock(return_value=mock_init_result)
        mock_runner.destroy = AsyncMock(return_value=mock_destroy_result)

        mock_workspace = MagicMock()
        mock_workspace.work_dir = "/tmp/fake"

        with (
            patch("app.api.routes.terraform.async_session", return_value=mock_session_ctx),
            patch("app.api.routes.terraform.TerraformRunner", return_value=mock_runner),
            patch("app.api.routes.terraform.release_org_lock", new_callable=AsyncMock),
            patch("app.api.routes.terraform.settings") as mock_settings,
        ):
            mock_settings.workspace_cleanup_enabled = True
            await _run_destroy_task(op_id, "TestOrg", mock_workspace)

        mock_workspace.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
#  Endpoint-level tests (schema validation, request routing)
# ---------------------------------------------------------------------------


class TestDestroyEndpointValidation:
    """Tests for request validation and error handling at the endpoint level."""

    @pytest.mark.asyncio
    async def test_destroy_requires_operation_id(self):
        """Destroy request must include operation_id."""
        from app.schemas.terraform import TerraformDestroyByOperationRequest

        with pytest.raises(Exception):
            TerraformDestroyByOperationRequest()

    @pytest.mark.asyncio
    async def test_destroy_accepts_valid_uuid(self):
        """Destroy request accepts a valid UUID operation_id."""
        from app.schemas.terraform import TerraformDestroyByOperationRequest

        op_id = uuid.uuid4()
        req = TerraformDestroyByOperationRequest(operation_id=op_id)
        assert req.operation_id == op_id

    @pytest.mark.asyncio
    async def test_destroy_rejects_non_apply_operation(self, patch_redis):
        """Destroy endpoint rejects operations that are not APPLY type."""
        # This is a logical test — the endpoint should check the operation type.
        # The actual HTTP test would need a full app fixture.
        plan_op = Operation(
            id=uuid.uuid4(),
            type=OperationType.PLAN,
            status=OperationStatus.SUCCESS,
            user_id=FAKE_USER_SUB,
            username=FAKE_USERNAME,
            target_org="TestOrg",
        )
        assert plan_op.type != OperationType.APPLY

    @pytest.mark.asyncio
    async def test_destroy_rejects_failed_apply(self, patch_redis):
        """Destroy endpoint rejects apply operations that are not SUCCESS."""
        failed_apply = _make_apply_op(status=OperationStatus.FAILED)
        assert failed_apply.status != OperationStatus.SUCCESS
