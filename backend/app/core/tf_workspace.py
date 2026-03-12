import shutil
import uuid
from pathlib import Path

from app.config import settings
from app.core.hcl_generator import HCLGenerator, _slug


class TerraformWorkspace:
    """Manages an isolated temporary directory for a single Terraform operation.

    Layout: {tf_workspace_base}/{org_slug}/{operation_id}/main.tf
    """

    def __init__(self, org_name: str, operation_id: uuid.UUID | None = None) -> None:
        self.org_name = org_name
        self.org_slug = _slug(org_name)
        self.operation_id = operation_id or uuid.uuid4()
        self.work_dir = (
            Path(settings.tf_workspace_base) / self.org_slug / str(self.operation_id)
        )
        self._generator = HCLGenerator()

    def create(self, config: dict) -> str:
        """Create the workspace directory, render HCL, write main.tf.

        Returns the rendered HCL string.
        """
        self.work_dir.mkdir(parents=True, exist_ok=True)
        hcl = self._generator.generate(config)
        (self.work_dir / "main.tf").write_text(hcl, encoding="utf-8")
        return hcl

    def cleanup(self) -> None:
        """Remove the workspace directory tree."""
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
