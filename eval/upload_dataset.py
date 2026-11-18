"""Upload the evaluation dataset (src/data/eval_dataset.json) to LangSmith.

Usage:
    python -m eval.upload_dataset            # upload
    python -m eval.upload_dataset --dry-run  # validate only, no network

Reads LANGSMITH_API_KEY and LANGSMITH_ENDPOINT from .env. The dataset name defaults to
"helpdesk-lite-eval" and can be changed with LANGSMITH_DATASET. If the dataset already exists the
script stops instead of adding duplicate examples; delete or rename it in LangSmith to refresh it.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from eval.dataset import DATASET_PATH, REPO_ROOT, load_examples

DEFAULT_DATASET_NAME = "helpdesk-lite-eval"
DESCRIPTION = "HelpDesk Lite: 10 IT support requests with expected action, citation and approval."


def dataset_name() -> str:
    return os.environ.get("LANGSMITH_DATASET", DEFAULT_DATASET_NAME)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="validate the file, do not upload")
    args = parser.parse_args()

    examples = load_examples()
    name = dataset_name()
    print(f"Loaded {len(examples)} examples from {DATASET_PATH.relative_to(REPO_ROOT)}")
    if args.dry_run:
        print(f"Dry run: would upload to dataset {name!r}")
        return 0

    if not os.environ.get("LANGSMITH_API_KEY"):
        print("LANGSMITH_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    from langsmith import Client

    client = Client()
    if client.has_dataset(dataset_name=name):
        print(f"Dataset {name!r} already exists; not uploading duplicates.", file=sys.stderr)
        return 1

    dataset = client.create_dataset(name, description=DESCRIPTION)
    client.create_examples(
        dataset_id=dataset.id,
        inputs=[e["inputs"] for e in examples],
        outputs=[e["outputs"] for e in examples],
        metadata=[e["metadata"] for e in examples],
    )
    print(f"Created dataset {name!r} with {len(examples)} examples")
    return 0


if __name__ == "__main__":
    sys.exit(main())
