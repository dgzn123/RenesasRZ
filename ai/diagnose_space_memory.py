import os
import sys
import time
from pathlib import Path

try:
    import psutil
except Exception as exc:
    print("psutil import failed:", exc)
    psutil = None


def fmt(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.2f} {units[i]}"


def safe_size(path: Path, limit_files=300000):
    total = 0
    count = 0
    errors = 0
    try:
        if path.is_file():
            return path.stat().st_size, 1, 0
        for root, dirs, files in os.walk(path, topdown=True):
            count += len(files)
            if count > limit_files:
                return total, count, errors + 1
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except Exception:
                    errors += 1
    except Exception:
        errors += 1
    return total, count, errors


def print_disk():
    print("=== DISK USAGE ===")
    if psutil:
        for p in psutil.disk_partitions(all=False):
            if p.device.upper().startswith("C:"):
                u = psutil.disk_usage(p.mountpoint)
                print(f"{p.device} total={fmt(u.total)} used={fmt(u.used)} free={fmt(u.free)} percent={u.percent}%")

    print("\n=== C:\\ ROOT LARGE ENTRIES ===")
    entries = []
    for p in Path("C:/").iterdir():
        size, count, errors = safe_size(p)
        entries.append((size, str(p), count, errors))
    for size, path, count, errors in sorted(entries, reverse=True)[:40]:
        print(f"{fmt(size):>10} files={count:<8} errors={errors:<4} {path}")

    print("\n=== KNOWN SPACE SUSPECTS ===")
    suspects = [
        "C:/pagefile.sys",
        "C:/hiberfil.sys",
        "C:/swapfile.sys",
        "C:/$Recycle.Bin",
        "C:/Users/Heda/Desktop/index",
        "C:/Users/Heda/Desktop/index/ai",
        "C:/Users/Heda/Desktop/index/Ultralytics",
        "C:/Users/Heda/.cache",
        "C:/Users/Heda/.conda",
        "C:/Users/Heda/AppData/Local/Temp",
        "C:/Users/Heda/AppData/Local/pip",
        "C:/Users/Heda/AppData/Local/Ultralytics",
        "C:/Users/Heda/AppData/Roaming/Ultralytics",
        "C:/ProgramData/NVIDIA Corporation",
        "C:/Users/Heda/AppData/Local/NVIDIA",
        "C:/Users/Heda/AppData/Local/NVIDIA Corporation",
        "D:/Anaconda/pkgs",
        "D:/Anaconda/envs/route-seg",
    ]
    for s in suspects:
        p = Path(s)
        if p.exists():
            size, count, errors = safe_size(p)
            print(f"{fmt(size):>10} files={count:<8} errors={errors:<4} {s}")
        else:
            print(f"{'missing':>10} {s}")


def print_memory():
    print("\n=== MEMORY ===")
    if not psutil:
        return
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    print(f"RAM total={fmt(vm.total)} used={fmt(vm.used)} available={fmt(vm.available)} percent={vm.percent}%")
    print(f"SWAP total={fmt(sm.total)} used={fmt(sm.used)} free={fmt(sm.free)} percent={sm.percent}%")

    print("\n=== TOP PROCESSES BY RSS ===")
    rows = []
    for proc in psutil.process_iter(["pid", "name", "exe", "memory_info", "memory_percent", "cmdline"]):
        try:
            info = proc.info
            rss = info["memory_info"].rss
            rows.append((rss, info["pid"], info["name"], info.get("exe"), info.get("cmdline")))
        except Exception:
            pass
    for rss, pid, name, exe, cmdline in sorted(rows, reverse=True)[:40]:
        cmd = " ".join(cmdline or [])
        print(f"{fmt(rss):>10} pid={pid:<7} name={name:<28} exe={exe} cmd={cmd[:180]}")


def sample_memory(seconds=20):
    if not psutil:
        return
    print(f"\n=== MEMORY GROWTH SAMPLE ({seconds}s) ===")
    before = {}
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            before[proc.info["pid"]] = (proc.info["name"], proc.info["memory_info"].rss)
        except Exception:
            pass
    time.sleep(seconds)
    changes = []
    for proc in psutil.process_iter(["pid", "name", "exe", "memory_info", "cmdline"]):
        try:
            pid = proc.info["pid"]
            old = before.get(pid, (proc.info["name"], 0))[1]
            new = proc.info["memory_info"].rss
            changes.append((new - old, new, pid, proc.info["name"], proc.info.get("exe"), proc.info.get("cmdline")))
        except Exception:
            pass
    for delta, rss, pid, name, exe, cmdline in sorted(changes, reverse=True)[:25]:
        if abs(delta) < 10 * 1024 * 1024:
            continue
        cmd = " ".join(cmdline or [])
        print(f"delta={fmt(delta):>10} rss={fmt(rss):>10} pid={pid:<7} name={name:<25} exe={exe} cmd={cmd[:160]}")


if __name__ == "__main__":
    print("python:", sys.executable)
    print_disk()
    print_memory()
    sample_memory(20)
