"""Scan tracked source without printing matched credentials or uploading files."""

import re
import subprocess

PATTERN = re.compile(
    rb"(?:gsk_[A-Za-z0-9]{25,}|gh[pousr]_[A-Za-z0-9_]{25,}|sk-proj-[A-Za-z0-9_-]{25,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\0")  # noqa: S603,S607
    rejected = []
    for raw in names:
        if not raw:
            continue
        name = raw.decode()
        if name == ".env" or name.startswith(
            (".work/", "reports/", "PL_Capital_Codex_Master_Prompt")
        ):
            rejected.append(name)
            continue
        content = subprocess.check_output(["git", "show", ":" + name])  # noqa: S603,S607
        if PATTERN.search(content):
            rejected.append(name)
    if rejected:
        print("Credential/path scan failed: " + ", ".join(rejected))
        return 1
    print("Tracked-source credential scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
