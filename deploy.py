"""Deploys the API to a Hugging Face Space (docker sdk).

    python deploy.py            upload the code, the space rebuilds on its own
    python deploy.py --secrets  also (re)set the api keys as space secrets

Reads HF_TOKEN, HF_SPACE and GEMINI_API_KEY from .env.
"""

import secrets
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"

# only what the container needs, nothing else leaves the machine
FILES = ["Dockerfile", "requirements.txt", "data/profile.md"]
FILES += [str(p.relative_to(ROOT)) for p in sorted((ROOT / "app").rglob("*.py"))]
FILES += [str(p.relative_to(ROOT)) for p in sorted((ROOT / "prompts").glob("*.md"))]


def read_env() -> dict[str, str]:
    lines = ENV_FILE.read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


def main() -> None:
    env = read_env()
    space = env["HF_SPACE"]
    api = HfApi(token=env["HF_TOKEN"])
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)

    if "--secrets" in sys.argv:
        # the production key is different from the local one and lives only in .env and the space
        agent_key = env.get("PROD_AGENT_API_KEY")
        if not agent_key:
            agent_key = secrets.token_hex(24)
            with ENV_FILE.open("a") as f:
                f.write(f"\nPROD_AGENT_API_KEY={agent_key}\n")
        api.add_space_secret(space, "GEMINI_API_KEY", env["GEMINI_API_KEY"])
        api.add_space_secret(space, "AGENT_API_KEY", agent_key)
        print("secrets set, production key saved in .env as PROD_AGENT_API_KEY")

    ops = [CommitOperationAdd(path_in_repo=f, path_or_fileobj=str(ROOT / f)) for f in FILES]
    ops.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(ROOT / "hf_space.md")))
    api.create_commit(space, ops, commit_message="deploy", repo_type="space")

    user, name = space.split("/")
    print(f"uploaded {len(ops)} files. building at https://huggingface.co/spaces/{space}")
    print(f"api url: https://{user}-{name}.hf.space/v1".lower())


if __name__ == "__main__":
    main()
