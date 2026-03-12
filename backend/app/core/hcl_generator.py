import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

# Ordered list of config sections and their corresponding template files.
# The generator renders them in this order so the output reads logically:
# provider/backend first, then org, then vdc, etc.
_SECTION_TEMPLATES: list[tuple[str, str]] = [
    ("org", "organization.tf.j2"),
    ("vdc", "vdc.tf.j2"),
]


def _slug(value: str) -> str:
    """Convert a human-readable name to a valid Terraform identifier.

    Example: "My Org (prod)" -> "my_org_prod"
    """
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value or "resource"


def _build_jinja_env(templates_dir: Path | None = None) -> Environment:
    loader = FileSystemLoader(str(templates_dir or TEMPLATES_DIR))
    env = Environment(
        loader=loader,
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["slug"] = _slug
    return env


class HCLGenerator:
    """Renders a complete .tf file from a frontend config dict using Jinja2."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._env = _build_jinja_env(templates_dir)

    def generate(self, config: dict[str, Any]) -> str:
        """Accept the full form-state config and return a combined HCL string.

        The config dict is expected to have optional top-level keys like:
            {
              "provider": { ... },
              "backend": { ... },
              "org": { "name": "...", ... },
              "vdc": { "name": "...", "provider_vdc_name": "...", ... },
            }

        Only sections present in the config are rendered.
        """
        # Provide empty-dict defaults for top-level keys so Jinja2 templates
        # can safely use `backend.bucket | default(...)` even when the
        # caller omits entire sections.
        ctx: dict[str, Any] = {
            "provider": {},
            "backend": {},
        }
        ctx.update(config)

        blocks: list[str] = []

        # 1. Always render the base provider/backend block.
        base_tpl = self._env.get_template("base.tf.j2")
        blocks.append(base_tpl.render(**ctx))

        # 2. Render each resource section if the key is present in config.
        for section_key, template_name in _SECTION_TEMPLATES:
            if section_key not in ctx:
                continue
            tpl = self._env.get_template(template_name)
            # Pass the full context so templates can cross-reference
            # (e.g., vdc.tf.j2 can reference org.name for the org attribute).
            blocks.append(tpl.render(**ctx))

        return "\n".join(blocks)
