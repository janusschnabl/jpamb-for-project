"""Write guarded sources to a separate folder and compile them."""

import os
import shutil
import subprocess
from pathlib import Path

import jpamb
from jpamb.utils import DockerRunner

IMAGE = "ghcr.io/kalhauge/jvm2json:jdk-latest"


def output_folder(suite: jpamb.Suite, eff) -> Path:
    return suite.cache_folder(eff=eff) / "tier3"


def write_patched(suite: jpamb.Suite, patched: dict[Path, str], outdir: Path) -> Path:
    """A copy of all case sources, with the patched files replaced."""
    src = outdir / "src"
    if src.exists():
        shutil.rmtree(src)
    shutil.copytree(suite.sourcefiles_folder, src)
    for path, text in patched.items():
        (src / path.relative_to(suite.sourcefiles_folder)).write_text(text)
    return src


def compile_sources(suite: jpamb.Suite, eff, src: Path, outdir: Path) -> tuple[bool, str]:
    """Compile with javac in the JPAMB image. Returns (ok, compiler output)."""
    classes = outdir / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    rel = lambda p: p.relative_to(suite.workdir).as_posix()
    docker = DockerRunner.create(suite.workdir, IMAGE, eff=eff)
    cmd = [
        *docker.docker_cmd, "run", "--rm",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{docker.workfolder}:/workspace",
        docker.image,
        "javac", "-g", "-d", rel(classes),
        *(rel(p) for p in sorted(src.rglob("*.java"))),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return proc.returncode == 0, proc.stdout + proc.stderr
