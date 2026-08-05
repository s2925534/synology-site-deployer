from __future__ import annotations

import pytest

from synology_site.commands.create_storage_pool import (
    PROTECTED_HDD_MODELS,
    execute_storage_pool,
    plan_storage_pool,
    run_create_storage_pool,
)
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import RemoteCommandResult


def settings() -> Settings:
    return Settings(
        nas_host="192.0.2.10",
        nas_port=22,
        nas_user="deploy",
        nas_docker_root="/volume1/docker",
        nas_ssh_key_path=None,
        nas_ssh_password="secret",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
        default_framework="flask",
        restart_policy="unless-stopped",
        cf_api_token=None,
        cf_account_id=None,
        cf_zone_id=None,
        cf_zone_domain="example.com",
        cf_tunnel_id=None,
        cf_tunnel_name="my-nas-tunnel",
        db_mode="none",
        db_type="mariadb",
        db_image="mariadb:11",
        db_password_length=32,
        db_publish_port=False,
        db_host_port=None,
        allow_overwrite=False,
        dry_run=False,
    )


CACHE_ENUM = """************ Disk Info ***************
>> Disk id: 1
>> Disk path: /dev/nvme0n1
>> Disk model: Samsung SSD 9100 PRO 2TB
>> Total capacity: 1863.02 GB
************ Disk Info ***************
>> Disk id: 2
>> Disk path: /dev/nvme1n1
>> Disk model: Samsung SSD 9100 PRO 2TB
>> Total capacity: 1863.02 GB
"""

CACHE_ENUM_SINGLE = """************ Disk Info ***************
>> Disk id: 1
>> Disk path: /dev/nvme0n1
>> Disk model: Samsung SSD 9100 PRO 2TB
>> Total capacity: 1863.02 GB
"""

INTERNAL_ENUM = """************ Disk Info ***************
>> Disk id: 1
>> Disk path: /dev/sata1
>> Disk model: WD100EFGX-68CPLN0
>> Total capacity: 9314.00 GB
"""

MDSTAT_WITH_SATA_ARRAYS = """Personalities : [raid1] [raid10]
md2 : active raid10 sata2p3[0] sata5p3[3] sata3p3[2] sata1p3[4]
      19511425024 blocks super 1.2 64K chunks 2 near-copies [4/4] [UUUU]
"""


class FakeSSH:
    def __init__(
        self,
        *,
        model: str = "DS1525+",
        cache_enum: str = CACHE_ENUM,
        internal_enum: str = INTERNAL_ENUM,
        mdstat: str = "Personalities : [raid1]\n",
        blkid_signatures: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self.cache_enum = cache_enum
        self.internal_enum = internal_enum
        self.mdstat = mdstat
        self.blkid_signatures = blkid_signatures or {}
        self.commands: list[str] = []

    def __enter__(self) -> "FakeSSH":
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
        stdin: str | None = None,
    ) -> RemoteCommandResult:
        del timeout, stdin
        self.commands.append(command)

        if "syno_hw_version" in command:
            result = RemoteCommandResult(command, 0, self.model, "")
        elif "synodisk --enum -t cache" in command:
            result = RemoteCommandResult(command, 0, self.cache_enum, "")
        elif "synodisk --enum -t internal" in command:
            result = RemoteCommandResult(command, 0, self.internal_enum, "")
        elif "blkid" in command:
            device = command.split()[-1]
            sig = self.blkid_signatures.get(device, "")
            result = RemoteCommandResult(command, 0 if sig else 2, sig, "")
        elif "cat /proc/mdstat" in command:
            result = RemoteCommandResult(command, 0, self.mdstat, "")
        else:
            result = RemoteCommandResult(command, 0, "", "")

        if check and not result.ok:
            raise SynologySiteError(f"failed: {command}")
        return result


def test_requires_exactly_one_of_nvme_or_hdd() -> None:
    fake = FakeSSH()
    with pytest.raises(SynologySiteError, match="Exactly one of --nvme or --hdd"):
        plan_storage_pool(fake, nvme=True, hdd=True, raid_level="raid1")
    with pytest.raises(SynologySiteError, match="Exactly one of --nvme or --hdd"):
        plan_storage_pool(fake, nvme=False, hdd=False, raid_level="raid1")


def test_rejects_raid_level_not_allowed_for_nvme() -> None:
    fake = FakeSSH()
    with pytest.raises(SynologySiteError, match=r"--raid-level for --nvme"):
        plan_storage_pool(fake, nvme=True, hdd=False, raid_level="raid5")


def test_nvme_auto_detects_both_drives_for_raid1() -> None:
    fake = FakeSSH()

    selected = plan_storage_pool(fake, nvme=True, hdd=False, raid_level="raid1")

    assert selected == ("/dev/nvme0n1", "/dev/nvme1n1")


def test_basic_with_multiple_candidates_requires_explicit_device() -> None:
    fake = FakeSSH()
    with pytest.raises(SynologySiteError, match="pass --device"):
        plan_storage_pool(fake, nvme=True, hdd=False, raid_level="basic")


def test_basic_with_explicit_device_succeeds() -> None:
    fake = FakeSSH()

    selected = plan_storage_pool(
        fake, nvme=True, hdd=False, raid_level="basic", devices=("/dev/nvme0n1",)
    )

    assert selected == ("/dev/nvme0n1",)


def test_rejects_unknown_explicit_device() -> None:
    fake = FakeSSH()
    with pytest.raises(SynologySiteError, match="not found among detected"):
        plan_storage_pool(fake, nvme=True, hdd=False, raid_level="basic", devices=("/dev/nvme9n1",))


def test_enforces_minimum_drive_count() -> None:
    fake = FakeSSH(cache_enum=CACHE_ENUM_SINGLE)
    with pytest.raises(SynologySiteError, match="needs at least 2 drive"):
        plan_storage_pool(fake, nvme=True, hdd=False, raid_level="raid1")


def test_blocks_device_with_existing_filesystem_signature() -> None:
    fake = FakeSSH(blkid_signatures={"/dev/nvme0n1": '/dev/nvme0n1: TYPE="ext4"\n'})

    with pytest.raises(SynologySiteError, match="already look in use"):
        plan_storage_pool(fake, nvme=True, hdd=False, raid_level="raid1")


def test_blocks_device_already_in_raid_array() -> None:
    fake = FakeSSH(mdstat=MDSTAT_WITH_SATA_ARRAYS, model="DS920+")

    with pytest.raises(SynologySiteError, match="already appears as a RAID member"):
        plan_storage_pool(fake, nvme=False, hdd=True, raid_level="basic", devices=("/dev/sata1",))


def test_blocks_hdd_on_protected_model() -> None:
    assert "DS1525+" in PROTECTED_HDD_MODELS
    fake = FakeSSH(model="DS1525+")

    with pytest.raises(SynologySiteError, match="Refusing to run --hdd on DS1525"):
        plan_storage_pool(fake, nvme=False, hdd=True, raid_level="raid1")


def test_nvme_is_unaffected_by_protected_model_guard() -> None:
    fake = FakeSSH(model="DS1525+")

    selected = plan_storage_pool(fake, nvme=True, hdd=False, raid_level="raid1")

    assert selected == ("/dev/nvme0n1", "/dev/nvme1n1")


def test_execute_creates_pool_on_raw_devices_with_expected_commands() -> None:
    fake = FakeSSH()

    result = execute_storage_pool(
        fake,
        devices=("/dev/nvme0n1", "/dev/nvme1n1"),
        raid_level="raid1",
        description="NVMe RAID1",
    )

    assert result.devices == ("/dev/nvme0n1", "/dev/nvme1n1")
    # no separate partitioning step -- synostgpool partitions the raw devices itself
    assert not any("synopartition" in c or "synodisk --partition" in c for c in fake.commands)
    create_cmd = next(c for c in fake.commands if "synostgpool --create" in c)
    assert "-l raid1" in create_cmd
    assert "/dev/nvme0n1" in create_cmd
    assert "/dev/nvme1n1" in create_cmd
    assert "NVMe RAID1" in create_cmd


def test_run_create_storage_pool_returns_none_when_not_confirmed() -> None:
    fake = FakeSSH()

    result = run_create_storage_pool(
        settings(),
        nvme=True,
        hdd=False,
        raid_level="raid1",
        ssh_factory=lambda _settings, _password: fake,
        confirm=lambda _devices, _level: False,
    )

    assert result is None
    assert not any("synostgpool --create" in c for c in fake.commands)


def test_run_create_storage_pool_executes_when_confirmed() -> None:
    fake = FakeSSH()

    result = run_create_storage_pool(
        settings(),
        nvme=True,
        hdd=False,
        raid_level="raid1",
        ssh_factory=lambda _settings, _password: fake,
        confirm=lambda _devices, _level: True,
    )

    assert result is not None
    assert result.raid_level == "raid1"
    assert any("synostgpool --create" in c for c in fake.commands)
