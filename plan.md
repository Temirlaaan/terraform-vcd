# Шаг 2: Migration HCL Generator — Canonical JSON → HCL via Jinja2

## Контекст

Step 1 (Normalizer) готов: `normalizer.py` (52 теста, defusedxml). Generator — следующий логический шаг: принимает canonical JSON от normalizer + параметры target (org, vdc, edge_id) и рендерит набор `.tf` файлов через Jinja2.

**Почему Generator, а не Fetcher:**
- Generator — чистая функция (JSON in, HCL out), аналогична `HCLGenerator` в `hcl_generator.py`
- Легко покрывается юнит-тестами без моков httpx
- После Generator готов полный pipeline для ручного тестирования

## Файлы для создания

### 1. Jinja2-шаблоны: `backend/templates/migration/`

#### 1.1 `provider.tf.j2`
Provider block + S3 backend для migration workspace:
```hcl
terraform {
  required_providers {
    vcd = {
      source  = "vmware/vcd"
      version = "~> 3.12"
    }
  }
  backend "s3" {
    bucket = "{{ backend_bucket | default('terraform-state') | hcl_escape }}"
    key    = "{{ state_key | hcl_escape }}"
    ...
  }
}
provider "vcd" {
  url      = var.vcd_url
  user     = var.vcd_user
  password = var.vcd_password
  org      = var.target_org
  allow_unverified_ssl = true
}
```

#### 1.2 `variables.tf.j2`
Переменные target org/vdc/edge с default-значениями из формы. Credentials через `TF_VAR_*`, без хардкода.

#### 1.3 `app_port_profiles.tf.j2`
- Системные профили (HTTPS, SSH и т.д.) → `data "vcd_nsxt_app_port_profile"` с `scope = "SYSTEM"`
- Кастомные профили (нестандартные порты) → `resource "vcd_nsxt_app_port_profile"` с `scope = "TENANT"`

#### 1.4 `nat.tf.j2`
Одно правило `vcd_nsxt_nat_rule` на каждое enabled NAT-правило:

| Поле NSX-V | DNAT (NSX-T) | SNAT (NSX-T) |
|---|---|---|
| `original_address` | `external_address` | `internal_address` |
| `translated_address` | `internal_address` | `external_address` |
| `original_port` | `dnat_external_port` | не используется |

`app_port_profile_id` ссылается на `data.` (системный) или `resource.` (кастомный).

#### 1.5 `firewall.tf.j2`
- IP-адреса враппятся в `vcd_nsxt_ip_set` (по одному на source/destination каждого правила)
- Один `resource "vcd_nsxt_firewall" "migrated"` с множеством вложенных `rule {}` блоков
- Системные правила (`is_system=true`) и disabled правила — пропускаются

#### 1.6 `static_routes.tf.j2`
По одному `vcd_nsxt_edgegateway_static_route` на каждый маршрут.

### 2. `backend/app/migration/generator.py`

**Публичный API:**
```python
class MigrationHCLGenerator:
    def __init__(self, templates_dir: Path | None = None) -> None: ...

    def generate(
        self,
        normalized: dict[str, Any],
        target_org_name: str,
        target_vdc_name: str,
        target_edge_id: str,
    ) -> dict[str, str]:
        """Returns dict: filename → HCL content."""

    def generate_combined(...) -> str:
        """Single HCL string for frontend preview."""
```

**Внутренние методы:**
- `_build_context()` — собирает Jinja2 context из normalized JSON + target params
- `_enrich_nat_rules()` — добавляет `_is_system_profile` к NAT-правилам (вычисляемое поле, не меняет схему normalizer)

**Переиспользование из `hcl_generator.py`:**
- `_build_jinja_env()` — создание Jinja2 Environment с фильтрами `slug`, `hcl_escape`
- `_slug()` — нормализация имён ресурсов

**State key:** `migration/{org_slug}/{edge_slug}/terraform.tfstate`

### 3. `backend/tests/test_migration_generator.py`

**Тестовые классы:**

```
class TestMigrationHCLGenerator:
    # --- Structure ---
    - test_generates_all_expected_files
    - test_generate_combined_returns_string

    # --- Variables & Provider ---
    - test_variables_contain_target_defaults
    - test_provider_block_has_s3_backend
    - test_provider_credentials_not_hardcoded

    # --- App Port Profiles ---
    - test_system_profile_as_data_source (tcp_443 → data, scope=SYSTEM)
    - test_custom_profile_as_resource (udp_9000-10999 → resource, scope=TENANT)
    - test_profile_dedup_single_resource

    # --- NAT Rules ---
    - test_dnat_rule_address_mapping (original→external, translated→internal)
    - test_snat_rule_address_mapping (original→internal, translated→external)
    - test_dnat_external_port_rendered
    - test_nat_app_port_profile_ref_system (data.vcd_nsxt_app_port_profile.tcp_443.id)
    - test_nat_app_port_profile_ref_custom (vcd_nsxt_app_port_profile.udp_9000_10999.id)
    - test_disabled_nat_rules_skipped
    - test_nat_description_hcl_escaped

    # --- Firewall ---
    - test_firewall_renders_single_resource
    - test_system_rules_skipped
    - test_ip_set_created_for_source
    - test_ip_set_created_for_destination
    - test_firewall_rule_references_ip_set
    - test_action_mapping_preserved

    # --- Static Routes ---
    - test_static_routes_rendered (2 resources)
    - test_route_fields_correct
    - test_route_description_escaped

    # --- Edge Cases ---
    - test_empty_firewall_rules
    - test_empty_nat_rules
    - test_empty_static_routes
    - test_hcl_escape_special_chars
```

**~25-28 тестов.** Фикстура: результат `normalize_edge_snapshot()` из фикстур normalizer тестов.

## Пример ожидаемого HCL

Target: org="MyOrg", vdc="MyVDC", edge_id="urn:vcloud:gateway:new-edge-123"

**app_port_profiles.tf:**
```hcl
data "vcd_nsxt_app_port_profile" "tcp_443" {
  name  = "HTTPS"
  scope = "SYSTEM"
}

resource "vcd_nsxt_app_port_profile" "udp_9000_10999" {
  name        = "ttc_nat_udp_9000_10999"
  scope       = "TENANT"
  org         = var.target_org
  context_id  = var.target_edge_id
  ...
}
```

**nat.tf (DNAT):**
```hcl
resource "vcd_nsxt_nat_rule" "rule_200825" {
  org                 = var.target_org
  edge_gateway_id     = var.target_edge_id
  name                = "Access to SSH"
  rule_type           = "DNAT"
  external_address    = "37.208.43.38"
  internal_address    = "10.10.0.19"
  dnat_external_port  = "443"
  app_port_profile_id = data.vcd_nsxt_app_port_profile.tcp_443.id
}
```

**firewall.tf:**
```hcl
resource "vcd_nsxt_ip_set" "fw_135393_src" {
  ...
  ip_addresses = ["10.121.24.3/32", "10.121.44.0/24", "10.121.43.0/24"]
}

resource "vcd_nsxt_firewall" "migrated" {
  org             = var.target_org
  edge_gateway_id = var.target_edge_id

  rule {
    name        = "New Rule"
    action      = "ALLOW"
    source_ids  = [vcd_nsxt_ip_set.fw_135393_src.id]
    ...
  }
}
```

## Порядок реализации (TDD)

1. Создать `backend/templates/migration/` — все 6 `.tf.j2` шаблонов
2. Написать тесты `test_migration_generator.py` (RED)
3. Создать `generator.py` с `MigrationHCLGenerator` (GREEN)
4. Прогнать все тесты, итерировать
5. Рефактор: < 300 строк, docstrings

## Зависимости

- `_build_jinja_env`, `_slug` из `hcl_generator.py` — только импорт, без изменений
- `defusedxml` — уже установлен
- Новых зависимостей нет

## Verification

```bash
cd backend && python3 -m pytest tests/test_migration_generator.py tests/test_migration_normalizer.py -v
```
