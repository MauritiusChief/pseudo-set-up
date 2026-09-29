"""Print an endless, harmless simulation of a pip install on Windows.

Call structure:
    main
    |-- parse_args
    |-- Terminal
    `-- run_forever
        |-- dependency_order
        |-- generate_virtual_packages
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

PREFIXES = [
    "py", "fast", "async", "super", "micro", "hyper", "neo", "data",
    "cloud", "web", "auto", "smart", "open", "simple", "tiny", "mega",
]

BODYS = [
    "core", "utils", "client", "server", "parser", "engine", "kit",
    "tools", "lib", "api", "stream", "cache", "model", "runtime",
    "bridge", "flow", "stack", "worker", "codec", "store",
]

SUFFIXES = [
    "", "-ng", "-plus", "-ext", "-pro", "-cli", "-sdk", "-py",
    "-common", "-helper", "-extra",
]

MIN_SPEED_MB_S = 0.2
MAX_SPEED_MB_S = 4.0
PROGRESS_REFRESH_SECONDS = 0.2


@dataclass(frozen=True)
class Package:
    """Simulated format of package."""
    name: str
    version: str
    size_mb: float
    dependencies: tuple
    native: bool = False


@dataclass
class NetworkState:
    """Hold the download speed shared by every package in the process."""
    # Currently displayed and applied transfer rate
    speed_mb_s: float
    # The slowly moving destination
    target_mb_s: float

    def update(self) -> float:
        """Advance the global speed by one animation frame and return it.

        A target change represents network conditions shifting between downloads
        or during a large file. Both values remain inside the configured slow
        network range so ETA and transferred-byte calculations stay plausible.
        """
        if random.random() < 0.03:
            self.target_mb_s = random.uniform(MIN_SPEED_MB_S, MAX_SPEED_MB_S)

        drift = (self.target_mb_s - self.speed_mb_s) * 0.08
        jitter = random.uniform(-0.06, 0.06)
        self.speed_mb_s = max(
            MIN_SPEED_MB_S,
            min(self.speed_mb_s + drift + jitter, MAX_SPEED_MB_S),
        )
        return self.speed_mb_s


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
    BAR_COMPLETE = "\033[38;2;249;38;114m"
    BAR_FINISHED = "\033[38;2;114;156;31m"
    BAR_BACK = "\033[38;5;237m"
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


def clock_text(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    return "{}:{:02d}:{:02d}".format(
        hours,
        remaining_minutes,
        remaining_seconds,
    )


def progress_bar(
    terminal: Terminal,
    ratio: float,
    width: int,
    is_finished: bool = False,
) -> str:
    """Build the colored bar shared by download and installation progress.

    This follows Rich's progress-bar cell algorithm and exact default colors.
    Complete cells are pink ``━`` characters, a half cell is a pink ``╸``, and
    ``╺`` belongs to the gray unfinished region. A finished download replaces
    all segments with one solid yellow-green bar.
    """
    ratio = max(0.0, min(ratio, 1.0))
    if is_finished:
        return terminal.paint("━" * width, terminal.BAR_FINISHED)

    complete_halves = int(width * 2 * ratio)
    complete_bars = complete_halves // 2
    has_half_bar = complete_halves % 2
    parts = []

    if complete_bars:
        parts.append(terminal.paint("━" * complete_bars, terminal.BAR_COMPLETE))
    if has_half_bar:
        parts.append(terminal.paint("╸", terminal.BAR_COMPLETE))

    remaining = width - complete_bars - has_half_bar
    if remaining and not has_half_bar and complete_bars:
        parts.append(terminal.paint("╺", terminal.BAR_BACK))
        remaining -= 1
    if remaining:
        parts.append(terminal.paint("━" * remaining, terminal.BAR_BACK))

    return "".join(parts)


def animate_task(
    terminal: Terminal,
    label: str,
    minimum: float = 0.45,
    maximum: float = 1.15,
) -> None:
    """Render a spinner-style task that finishes after a random duration.

    Interactive terminals receive an in-place, white spinner in the same
    trailing position later occupied by ``done``. Redirected output skips
    animation and emits only the final line, keeping captured logs compact.
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
        marker = frames[frame % len(frames)]
        terminal.status("{} ... {}".format(label, marker))
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
    network: NetworkState,
) -> None:
    """Render a download driven by the process-wide network speed.

    Each frame integrates the changing speed over elapsed real time, then derives
    progress and ETA from the transferred amount. Files expected to finish before
    Rich's first refresh are allowed to complete without displaying a progress
    line. Larger downloads retain the colored completed state in captured output.
    """
    terminal.line("  Downloading {} ({})".format(filename, human_size(size_mb)))
    estimated_duration = size_mb / max(network.speed_mb_s, MIN_SPEED_MB_S)
    if estimated_duration < PROGRESS_REFRESH_SECONDS:
        time.sleep(estimated_duration)
        network.update()
        return

    started = time.monotonic()
    previous = started
    downloaded_mb = 0.0
    width = 40 if pip_version >= 26 else 30

    while True:
        now = time.monotonic()
        frame_seconds = now - previous
        previous = now
        speed_mb_s = network.update()
        downloaded_mb = min(
            size_mb,
            downloaded_mb + speed_mb_s * frame_seconds,
        )
        elapsed = now - started
        ratio = downloaded_mb / size_mb

        # Determin size format
        if size_mb < 1.0:
            total = size_mb * 1024
            downloaded = downloaded_mb * 1024
            amount = "{:>5.1f}/{:.1f} kB".format(downloaded, total)
        else:
            amount = "{:>5.1f}/{:.1f} MB".format(downloaded_mb, size_mb)

        # Determin speed format
        if speed_mb_s < 1.0:
            rate = "{:>5.1f} kB/s".format(speed_mb_s * 1024)
        else:
            rate = "{:>5.1f} MB/s".format(speed_mb_s)

        is_finished = ratio >= 1.0
        # Determin ETA style
        if is_finished:
            eta_label = ""
            clock = terminal.paint(clock_text(elapsed), terminal.YELLOW)
        else:
            eta_label = "eta"
            remaining_seconds = (size_mb - downloaded_mb) / speed_mb_s
            clock = terminal.paint(clock_text(remaining_seconds), terminal.CYAN)

        progress = "   {} {} {} {} {}".format(
            progress_bar(terminal, ratio, width, is_finished),
            terminal.paint(amount, terminal.GREEN),
            terminal.paint(rate, terminal.RED),
            eta_label,
            clock,
        )
        terminal.status(progress)
        if is_finished:
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


def generate_virtual_packages(
    count: int,
    catalog: dict[str, Package],
    dependency_candidates: list[str],
) -> list[Package]:
    """Create or reuse natural-looking fictional packages for one batch.

    New names receive a stable package definition in the
    process-wide virtual catalog; if a name appears again later, its version,
    size, dependencies, and wheel type remain unchanged. Real package names and
    duplicates within the current batch are rejected.
    """
    packages = []
    selected_names = set()

    while len(packages) < count:
        name = random.choice(PREFIXES) + random.choice(BODYS) + random.choice(SUFFIXES)
        if name in PACKAGES or name in selected_names:
            continue

        package = catalog.get(name)
        if package is None:
            major = random.choice((0, 0, 0, 1, 1, 2, 3, 4))
            version = "{}.{}.{}".format(
                major,
                random.randint(0, 24),
                random.randint(0, 18),
            )

            size_roll = random.random()
            if size_roll < 0.65:
                size_mb = random.uniform(0.01, 0.50)
            elif size_roll < 0.92:
                size_mb = random.uniform(0.50, 5.0)
            else:
                size_mb = random.uniform(5.0, 30.0)

            dependency_count = random.randint(
                0,
                min(3, len(dependency_candidates)),
            )
            dependencies = tuple(
                random.sample(dependency_candidates, dependency_count)
            )
            package = Package(
                name,
                version,
                round(size_mb, 2),
                dependencies,
                random.random() < 0.22,
            )
            catalog[name] = package

        packages.append(package)
        selected_names.add(name)

    return packages


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
    network: NetworkState,
) -> None:
    """Render collection and track packages that need wheel builds.

    The function may show:
    - resolver backtracking
    - a network retry
    - a cache hit
    - or a normal wheel download

    Native packages sometimes take the slower source-distribution path; those packages are appended to ``built`` so the
    later build stage can render their wheel creation. 
    ``network`` is shared by real and fictional packages, so each non-cached download inherits the speed
    reached by the previous one.
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
        animate_download(terminal, filename, size, pip_version, network)

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
    dependency installation sequence. Pip 25 and newer styles receive an
    in-place magenta progress bar, a green package counter, and the active
    package name in brackets. The completed status line is removed rather than
    retained, and no success line is printed before the next batch begins.
    """
    names = [package.name for package in reversed(packages)]
    terminal.line("Installing collected packages: {}".format(", ".join(names)))

    # pip 25.1 introduced a transient installation progress display.
    if pip_version >= 25:
        duration = random.uniform(1.2, 2.6)
        started = time.monotonic()
        width = 40 if pip_version >= 26 else 30
        while time.monotonic() - started < duration:
            ratio = min((time.monotonic() - started) / duration, 1.0)
            count = min(len(names), int(ratio * len(names)) + 1)
            terminal.status(
                "{} {} [{}]".format(
                    progress_bar(terminal, count / len(names), width),
                    terminal.paint("{}/{}".format(count, len(names)), terminal.GREEN),
                    names[count - 1],
                )
            )
            time.sleep(0.10)
        terminal.clear_status()
    else:
        time.sleep(random.uniform(0.8, 1.8))


def run_forever(args: argparse.Namespace, terminal: Terminal) -> NoReturn:
    """Continuously select and render simulated installation batches.

    Root packages are shuffled and consumed in cycles. Every batch mixes one to
    four stable fictional packages into its real dependency trees, then passes
    through collection, source-wheel building, and installation. One network
    state carries changing download speed across every batch.
    """
    terminal.line("Looking in indexes: https://pypi.org/simple")
    # Holds root level packages, which introduce other dependent packages 
    roots = []
    virtual_catalog = {}
    network = NetworkState(
        random.uniform(MIN_SPEED_MB_S, MAX_SPEED_MB_S),
        random.uniform(MIN_SPEED_MB_S, MAX_SPEED_MB_S),
    )

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
        virtual_packages = generate_virtual_packages(
            random.randint(1, 4),
            virtual_catalog,
            names,
        )
        # Scatter fictional packages through real collection output.
        for package in virtual_packages:
            packages.insert(random.randint(0, len(packages)), package)

        for package in packages:
            collect_package(
                terminal,
                package,
                args.python_version,
                args.pip_version,
                built,
                network,
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
