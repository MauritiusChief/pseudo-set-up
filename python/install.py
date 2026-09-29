"""Print an endless, harmless simulation of a pip install on Windows.

Call structure:
    main
    |-- parse_args
    |-- Terminal
    `-- run_forever
        |-- dependency_order
        |-- collect_package
        |   |-- maybe_backtrack
        |   |-- maybe_retry
        |   |-- animate_download
        |   `-- animate_task
        |-- build_wheels
        |   `-- animate_task
        `-- install_batch

Only main controls process lifetime. run_forever selects simulated dependency
batches, while the collection, build, and installation functions only render
one stage of a batch. No function performs network or package-manager calls.
"""

import argparse
import ctypes
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn


PYTHON_TO_PIP = {
    "3.9": 22,
    "3.10": 23,
    "3.11": 24,
    "3.12": 25,
    "3.13": 26,
    "3.14": 26,
}

# These ranges keep manually selected combinations plausible. Pip 26 means
# 26.0.x under Python 3.9, since later 26.x releases dropped Python 3.9.
COMPATIBLE_PIP = {
    "3.9": range(22, 27),
    "3.10": range(22, 27),
    "3.11": range(22, 27),
    "3.12": range(23, 27),
    "3.13": range(24, 27),
    "3.14": range(25, 27),
}


@dataclass(frozen=True)
class Package:
    """Simulated format of package."""
    name: str
    version: str
    size_mb: float
    dependencies: tuple
    native: bool = False


# A fixed catalog produces recognizable dependency chains while selection,
# timing, cache hits, and build paths vary from one run to the next.
PACKAGES = {
    "fastapi": Package("fastapi", "0.118.0", 0.10, ("starlette", "pydantic", "typing-extensions")),
    "starlette": Package("starlette", "0.48.0", 0.07, ("anyio",)),
    "pydantic": Package("pydantic", "2.11.9", 0.43, ("annotated-types", "pydantic-core", "typing-extensions")),
    "pydantic-core": Package("pydantic-core", "2.33.2", 1.95, (), True),
    "annotated-types": Package("annotated-types", "0.7.0", 0.01, ()),
    "typing-extensions": Package("typing-extensions", "4.15.0", 0.04, ()),
    "anyio": Package("anyio", "4.11.0", 0.11, ("idna", "sniffio", "typing-extensions")),
    "sniffio": Package("sniffio", "1.3.1", 0.01, ()),
    "uvicorn": Package("uvicorn", "0.37.0", 0.07, ("click", "h11")),
    "click": Package("click", "8.3.0", 0.11, ()),
    "h11": Package("h11", "0.16.0", 0.04, ()),
    "requests": Package("requests", "2.32.5", 0.06, ("charset-normalizer", "idna", "urllib3", "certifi")),
    "charset-normalizer": Package("charset-normalizer", "3.4.3", 0.11, (), True),
    "idna": Package("idna", "3.10", 0.07, ()),
    "urllib3": Package("urllib3", "2.5.0", 0.13, ()),
    "certifi": Package("certifi", "2026.8.3", 0.16, ()),
    "pandas": Package("pandas", "2.3.2", 11.2, ("numpy", "python-dateutil", "pytz", "tzdata"), True),
    "numpy": Package("numpy", "2.3.3", 12.8, (), True),
    "python-dateutil": Package("python-dateutil", "2.9.0.post0", 0.23, ("six",)),
    "six": Package("six", "1.17.0", 0.01, ()),
    "pytz": Package("pytz", "2026.2", 0.50, ()),
    "tzdata": Package("tzdata", "2026.2", 0.34, ()),
    "scipy": Package("scipy", "1.16.2", 35.9, ("numpy",), True),
    "sqlalchemy": Package("sqlalchemy", "2.0.43", 2.10, ("greenlet", "typing-extensions"), True),
    "greenlet": Package("greenlet", "3.2.4", 0.30, (), True),
    "cryptography": Package("cryptography", "46.0.1", 3.50, ("cffi",), True),
    "cffi": Package("cffi", "2.0.0", 0.18, ("pycparser",), True),
    "pycparser": Package("pycparser", "2.23", 0.12, ()),
    "orjson": Package("orjson", "3.11.3", 0.14, (), True),
    "aiohttp": Package("aiohttp", "3.12.15", 1.70, ("attrs", "frozenlist", "multidict", "yarl"), True),
    "attrs": Package("attrs", "25.3.0", 0.06, ()),
    "frozenlist": Package("frozenlist", "1.7.0", 0.04, (), True),
    "multidict": Package("multidict", "6.6.4", 0.05, (), True),
    "yarl": Package("yarl", "1.20.1", 0.07, ("idna", "multidict", "propcache"), True),
    "propcache": Package("propcache", "0.3.2", 0.04, (), True),
}

ROOT_PACKAGES = ("fastapi", "uvicorn", "requests", "pandas", "scipy", "sqlalchemy", "cryptography", "orjson", "aiohttp")


class Terminal:
    RESET = "\033[0m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    DIM = "\033[2m"

    def __init__(self):
        self.interactive = sys.stdout.isatty()
        self.color = self.interactive and "NO_COLOR" not in os.environ
        self._status_visible = False
        self._enable_windows_ansi()

    def _enable_windows_ansi(self):
        """Enable ANSI escape processing for an interactive Windows console.

        Modern terminals usually support ANSI sequences already, but older
        Windows console hosts require this output-mode flag. Failure is ignored
        because color is cosmetic and plain output can continue normally.
        """
        if os.name != "nt" or not self.interactive:
            return
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except (AttributeError, OSError):
            pass

    def paint(self, text, color):
        return color + text + self.RESET if self.color else text

    def line(self, text=""):
        self.clear_status()
        print(text, flush=True)

    def status(self, text):
        if self.interactive:
            sys.stdout.write("\r\033[2K" + text)
            sys.stdout.flush()
            self._status_visible = True

    def clear_status(self):
        if self._status_visible:
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()
            self._status_visible = False


def parse_args() -> argparse.Namespace:
    """Resolve and validate the simulated Python and pip versions.

    - ``--python`` overrides the running interpreter for all generated tags and
    paths. 
    - ``--pip`` has higher priority than the Python-to-pip default mapping,
    but the final pair must still appear in ``COMPATIBLE_PIP``.
    """
    detected = "{}.{}".format(sys.version_info.major, sys.version_info.minor)
    parser = argparse.ArgumentParser(
        description="Continuously print a simulated pip installation without installing anything."
    )
    parser.add_argument(
        "--python",
        dest="python_version",
        choices=tuple(PYTHON_TO_PIP),
        help="simulated Python version (default: the interpreter running this script)",
    )
    parser.add_argument(
        "--pip",
        dest="pip_version",
        type=int,
        choices=range(22, 27),
        metavar="{22,23,24,25,26}",
        help="override the pip console style inferred from Python",
    )
    args = parser.parse_args()
    args.python_version = args.python_version or detected

    if args.python_version not in PYTHON_TO_PIP:
        parser.error(
            "Python {} is not mapped; select one with --python {{{}}}".format(
                args.python_version, ",".join(PYTHON_TO_PIP)
            )
        )

    args.pip_version = args.pip_version or PYTHON_TO_PIP[args.python_version]
    if args.pip_version not in COMPATIBLE_PIP[args.python_version]:
        parser.error(
            "pip {} is not compatible with simulated Python {}".format(
                args.pip_version, args.python_version
            )
        )
    return args


def wheel_tag(python_version):
    return "cp" + python_version.replace(".", "")


def distribution_name(package):
    return package.name.replace("-", "_")


def filename_for(
    package: Package,
    python_version: str,
    is_source: bool = False,
) -> str:
    """Build a plausible distribution filename for a simulated download.

    Source packages use ``.tar.gz``. Native wheels include the matching
    CPython interpreter and ABI tags, while pure Python wheels use the
    universal ``py3-none-any`` tag.
    """
    name = distribution_name(package)
    if is_source:
        return "{}-{}.tar.gz".format(name, package.version)
    if package.native:
        tag = wheel_tag(python_version)
        return "{}-{}-{}-{}-win_amd64.whl".format(name, package.version, tag, tag)
    return "{}-{}-py3-none-any.whl".format(name, package.version)


def human_size(size_mb):
    if size_mb < 0.1:
        return "{} kB".format(max(4, int(size_mb * 1024)))
    return "{:.1f} MB".format(size_mb)


def animate_task(
    terminal: Terminal,
    label: str,
    minimum: float = 0.45,
    maximum: float = 1.15,
) -> None:
    """Render a spinner-style task that finishes after a random duration.

    Interactive terminals receive an in-place spinner followed by a permanent
    completion line. Redirected output skips animation and emits only the final
    line, keeping captured logs compact.
    """
    duration = random.uniform(minimum, maximum)
    if not terminal.interactive:
        time.sleep(duration)
        terminal.line("{} ... done".format(label))
        return

    frames = ("-", "\\", "|", "/")
    started = time.monotonic()
    frame = 0
    while time.monotonic() - started < duration:
        marker = terminal.paint(frames[frame % len(frames)], terminal.CYAN)
        terminal.status("{} {} ...".format(marker, label))
        frame += 1
        time.sleep(0.09)
    terminal.status("{} ... done".format(label))
    terminal.clear_status()
    terminal.line("{} ... done".format(label))


def animate_download(
    terminal: Terminal,
    filename: str,
    size_mb: float,
    pip_version: int,
) -> None:
    """Render a timed download with pip-style size, speed, and ETA fields.

    Small files use kilobytes and larger files use megabytes. Progress updates
    overwrite one terminal line when interactive; redirected output receives
    only the completed progress line. No network request is made.
    """
    terminal.line("  Downloading {} ({})".format(filename, human_size(size_mb)))
    duration = random.uniform(0.65, 1.65) + min(size_mb / 35.0, 0.8)
    started = time.monotonic()
    width = 30 if pip_version >= 22 else 24

    while True:
        elapsed = time.monotonic() - started
        ratio = min(elapsed / duration, 1.0)
        completed = int(width * ratio)
        bar = "━" * completed + " " * (width - completed)
        if size_mb < 1.0:
            total = size_mb * 1024
            downloaded = total * ratio
            speed = total / max(duration, 0.1)
            amount = "{:>5.1f}/{:.1f} kB {:>5.1f} kB/s".format(
                downloaded, total, speed
            )
        else:
            downloaded = size_mb * ratio
            speed = size_mb / max(duration, 0.1)
            amount = "{:>5.1f}/{:.1f} MB {:>5.1f} MB/s".format(
                downloaded, size_mb, speed
            )
        eta = max(0, int(duration - elapsed + 0.99))
        progress = "     {} {} eta 0:00:{:02d}".format(
            terminal.paint(bar, terminal.CYAN), amount, eta
        )
        terminal.status(progress)
        if ratio >= 1.0:
            break
        time.sleep(0.08)

    # A redirected stream gets one completed progress line instead of frames.
    terminal.line(progress)


def maybe_retry(terminal: Terminal, package: Package) -> None:
    """Occasionally inject a recoverable network warning into collection.

    Most calls return immediately. Selected calls print a realistic pip timeout
    message and pause briefly, then allow collection to continue rather than
    raising an error or changing package state.
    """
    if random.random() >= 0.10:
        return
    retries = random.choice((2, 3, 4))
    warning = (
        "WARNING: Retrying (Retry(total={}, connect=None, read=None, redirect=None, "
        "status=None)) after connection broken by 'ReadTimeoutError': /packages/{}"
    ).format(retries, package.name)
    terminal.line(terminal.paint(warning, terminal.YELLOW))
    time.sleep(random.uniform(0.5, 1.1))


def dependency_order(root_name: str) -> list[str]:
    """Return a randomized depth-first package order starting at ``root_name``.

    Each package is included once, before its recursively visited dependencies.
    Dependency lists are shuffled so repeated batches remain visually varied,
    while the visited set prevents duplicate entries in shared dependency trees.
    """
    order = []
    visited = set()

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        order.append(name)
        dependencies = list(PACKAGES[name].dependencies)
        random.shuffle(dependencies)
        for dependency in dependencies:
            visit(dependency)

    visit(root_name)
    return order


def maybe_backtrack(terminal: Terminal, package: Package) -> None:
    """Occasionally render a harmless dependency-resolution backtrack.

    The output announces that pip is comparing versions, waits briefly, and
    prints metadata for a fabricated older release. It does not alter the
    package selected for the later download or installation stages.
    """
    if random.random() >= 0.12:
        return
    terminal.line(
        "INFO: pip is looking at multiple versions of {} to determine which version "
        "is compatible with other requirements. This could take a while.".format(package.name)
    )
    time.sleep(random.uniform(0.6, 1.3))
    older = package.version.rsplit(".", 1)[0] + "." + str(random.randint(0, 8))
    terminal.line("  Downloading {}-py3-none-any.whl.metadata (6.8 kB)".format(
        distribution_name(Package(package.name, older, 0, ())) + "-" + older
    ))


def collect_package(
    terminal: Terminal,
    package: Package,
    python_version: str,
    pip_version: int,
    built: list[Package],
) -> None:
    """Render collection and track packages that need wheel builds.

    The function may show:
    - resolver backtracking
    - a network retry
    - a cache hit
    - or a normal wheel download

    Native packages sometimes take the slower source-distribution path; those packages are appended to ``built`` so the
    later build stage can render their wheel creation.
    """
    terminal.line("Collecting {}".format(package.name))
    maybe_backtrack(terminal, package)
    maybe_retry(terminal, package)

    # Native projects occasionally take the slower source-distribution route.
    is_source = package.native and random.random() < 0.22
    filename = filename_for(package, python_version, is_source)
    size = package.size_mb * (0.45 if is_source else 1.0)

    if random.random() < 0.18 and not is_source:
        terminal.line("  Using cached {} ({})".format(filename, human_size(size)))
        time.sleep(random.uniform(0.12, 0.35))
    else:
        animate_download(terminal, filename, size, pip_version)

    if is_source:
        animate_task(terminal, "Installing build dependencies", 0.8, 1.8)
        animate_task(terminal, "Getting requirements to build wheel", 0.45, 1.0)
        animate_task(terminal, "Preparing metadata (pyproject.toml)", 0.5, 1.2)
        built.append(package)
    elif pip_version >= 23 and random.random() < 0.38:
        metadata = filename + ".metadata"
        terminal.line("  Downloading {} ({})".format(metadata, human_size(0.01)))
        time.sleep(random.uniform(0.12, 0.32))


def build_wheels(
    terminal: Terminal,
    packages: list[Package],
    python_version: str,
) -> None:
    """Render wheel builds for packages collected as source distributions.

    Each package receives a timed build task followed by a plausible wheel
    filename, byte size, SHA-256 digest, and Windows pip cache path. The cache
    path is display-only; no directory or wheel file is created.
    """
    if not packages:
        return
    terminal.line("Building wheels for collected packages: {}".format(
        ", ".join(package.name for package in packages)
    ))
    cache = Path.home() / "AppData" / "Local" / "pip" / "cache" / "wheels"
    for package in packages:
        animate_task(
            terminal,
            "Building wheel for {} (pyproject.toml)".format(package.name),
            1.1,
            2.5,
        )
        wheel = filename_for(package, python_version)
        wheel_bytes = int(package.size_mb * 1024 * 1024)
        digest = "".join(random.choice("0123456789abcdef") for _ in range(64))
        terminal.line(
            "  Created wheel for {}: filename={} size={} sha256={}".format(
                package.name, wheel, wheel_bytes, digest
            )
        )
        terminal.line("  Stored in directory: {}".format(cache))


def install_batch(
    terminal: Terminal,
    packages: list[Package],
    pip_version: int,
) -> None:
    """Render installation of one resolved package batch without completing it.

    Package names are displayed in reverse collection order to resemble pip's
    dependency installation sequence. Pip 25 and newer styles also receive an
    in-place package counter; older styles use a simple delay. No success line
    is printed, allowing the next batch to continue the simulation naturally.
    """
    names = [package.name for package in reversed(packages)]
    terminal.line("Installing collected packages: {}".format(", ".join(names)))

    # pip 25.1 introduced a transient installation progress display.
    if pip_version >= 25:
        duration = random.uniform(1.2, 2.6)
        started = time.monotonic()
        while time.monotonic() - started < duration:
            ratio = min((time.monotonic() - started) / duration, 1.0)
            count = min(len(names), int(ratio * len(names)) + 1)
            terminal.status(
                terminal.paint("Installing", terminal.GREEN)
                + " {} of {} packages".format(count, len(names))
            )
            time.sleep(0.10)
        terminal.clear_status()
    else:
        time.sleep(random.uniform(0.8, 1.8))


def run_forever(args: argparse.Namespace, terminal: Terminal) -> NoReturn:
    """Continuously select and render simulated installation batches.

    Root packages are shuffled and consumed in cycles. A batch contains the
    selected root's dependency tree and may include an unrelated second tree,
    then passes through collection, source-wheel building, and installation.
    """
    terminal.line("Looking in indexes: https://pypi.org/simple")
    # Holds root level packages, which introduce other dependent packages 
    roots = []

    while True:
        # Refill the root level packages if empty
        if not roots:
            roots = list(ROOT_PACKAGES)
            random.shuffle(roots)

        root = roots.pop()
        names = dependency_order(root)
        # Add an unrelated requirement occasionally, as large requirements files do.
        if random.random() < 0.45:
            extra = random.choice(ROOT_PACKAGES)
            for name in dependency_order(extra):
                if name not in names:
                    names.append(name)

        # Holds the packages that assigned as need-to-build
        built = []
        packages = [PACKAGES[name] for name in names]
        for package in packages:
            collect_package(
                terminal,
                package,
                args.python_version,
                args.pip_version,
                built,
            )
        # Simulate the build process
        build_wheels(terminal, built, args.python_version)
        # Simulate the install process
        install_batch(terminal, packages, args.pip_version)


def main() -> int:
    """Configure the console, parse options, and start the endless simulation."""
    try:
        # Keep Unicode progress bars intact in redirected or older Windows hosts.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        args = parse_args()
        terminal = Terminal()
        run_forever(args, terminal)
    except KeyboardInterrupt:
        terminal = locals().get("terminal") or Terminal()
        terminal.clear_status()
        terminal.line(terminal.paint("ERROR: Operation cancelled by user", terminal.RED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
