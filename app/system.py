"""Host system metrics (memory, swap, load, disk, uptime) read from /proc.

No external deps (psutil isn't installed); everything comes from the kernel's
procfs and os.statvfs so it works on the bare VPS.
"""
import os
from dataclasses import dataclass, field


@dataclass
class DiskUsage:
    mount: str
    total_bytes: int
    used_bytes: int
    free_bytes: int

    @property
    def percent(self) -> float:
        return (self.used_bytes / self.total_bytes * 100) if self.total_bytes else 0.0


@dataclass
class SystemStats:
    mem_total: int = 0
    mem_used: int = 0
    mem_available: int = 0
    swap_total: int = 0
    swap_used: int = 0
    load1: float = 0.0
    load5: float = 0.0
    load15: float = 0.0
    cpu_count: int = 0
    uptime_seconds: float = 0.0
    disks: list[DiskUsage] = field(default_factory=list)

    @property
    def mem_percent(self) -> float:
        return (self.mem_used / self.mem_total * 100) if self.mem_total else 0.0

    @property
    def swap_percent(self) -> float:
        return (self.swap_used / self.swap_total * 100) if self.swap_total else 0.0


# Disks worth surfacing: root (often near-full) and the mounted data volume.
_DISK_MOUNTS = ['/', '/mnt/volume_nyc3_01']


def _read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a dict of field -> bytes (values are in kB)."""
    info: dict[str, int] = {}
    with open('/proc/meminfo') as f:
        for line in f:
            key, _, rest = line.partition(':')
            parts = rest.split()
            if parts:
                info[key] = int(parts[0]) * 1024
    return info


def collect() -> SystemStats:
    stats = SystemStats()

    mem = _read_meminfo()
    stats.mem_total = mem.get('MemTotal', 0)
    stats.mem_available = mem.get('MemAvailable', 0)
    # "used" the way `free -h` reports it: total minus what's reclaimable.
    stats.mem_used = max(stats.mem_total - stats.mem_available, 0)
    stats.swap_total = mem.get('SwapTotal', 0)
    stats.swap_used = max(stats.swap_total - mem.get('SwapFree', 0), 0)

    with open('/proc/loadavg') as f:
        load1, load5, load15 = f.read().split()[:3]
    stats.load1, stats.load5, stats.load15 = float(load1), float(load5), float(load15)
    stats.cpu_count = os.cpu_count() or 1

    with open('/proc/uptime') as f:
        stats.uptime_seconds = float(f.read().split()[0])

    for mount in _DISK_MOUNTS:
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize  # available to non-root
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        stats.disks.append(DiskUsage(mount=mount, total_bytes=total, used_bytes=used, free_bytes=free))

    return stats
