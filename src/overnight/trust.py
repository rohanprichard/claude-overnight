"""Trusted repos: only blessed repositories may run overnight coding jobs,
since those run with acceptEdits and can execute shell commands."""

from pathlib import Path

from . import paths


def _trust_file() -> Path:
    return paths.base_dir() / "trusted_repos"


def _canonical(repo: str) -> str:
    return str(Path(repo).expanduser().resolve())


def list_trusted() -> list[str]:
    f = _trust_file()
    if not f.exists():
        return []
    return [line for line in f.read_text().splitlines() if line.strip()]


def is_trusted(repo: str) -> bool:
    return _canonical(repo) in list_trusted()


def trust(repo: str) -> str:
    paths.ensure_dirs()
    canonical = _canonical(repo)
    trusted = list_trusted()
    if canonical not in trusted:
        trusted.append(canonical)
        _trust_file().write_text("\n".join(trusted) + "\n")
    return canonical


def untrust(repo: str) -> bool:
    canonical = _canonical(repo)
    trusted = list_trusted()
    if canonical not in trusted:
        return False
    trusted.remove(canonical)
    _trust_file().write_text("\n".join(trusted) + ("\n" if trusted else ""))
    return True
