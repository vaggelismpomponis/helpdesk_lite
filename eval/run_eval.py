"""Run the 10 evaluation requests through the HelpDesk Lite graph and score them.

Usage:
    python -m eval.run_eval              # local score table
    python -m eval.run_eval -v           # also show interrupts and failure reasons
    python -m eval.run_eval --langsmith  # LangSmith experiment on the uploaded dataset

The graph is src/agent/graph.py with its current tools (mocks until #28). Clarification and
approval interrupts are answered from each example's inputs. With LANGSMITH_TRACING=true in .env,
every request is also traced. Exit code 0 only when every evaluator passes on every example.
"""

import argparse
import os
import sys
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
from langsmith import traceable

from eval.dataset import load_examples
from eval.evaluators import ALL_EVALUATORS, RunOutcome, evaluate
from eval.upload_dataset import dataset_name
from src.agent import nodes
from src.agent.graph import build_graph, config_for, decide, pending, reply, start

MAX_INTERRUPTS = 5


def _executed(proposal: Any) -> bool:
    return proposal is not None and proposal.action_id in nodes.EXECUTED_ACTION_IDS


@traceable(name="helpdesk_request")
def run_example(
    graph: Any,
    inputs: dict,
    *,
    example_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> tuple[RunOutcome, list[str]]:
    """Run one request, answering interrupts from the example inputs. Returns outcome and a log.

    Attaches thread_id, action_id, and evaluation tags to LangSmith trace runs and LangGraph config.
    """
    resolved_id = example_id or inputs.get("example_id")
    thread_id = inputs.get("thread_id") or str(uuid.uuid4())

    eval_tags = list(tags) if tags else ["evaluation"]
    if resolved_id and resolved_id not in eval_tags:
        eval_tags.append(resolved_id)

    run_meta: dict[str, Any] = {"thread_id": thread_id}
    if resolved_id:
        run_meta["example_id"] = resolved_id
    if metadata:
        run_meta.update(metadata)

    # Attach tracing metadata and tags to active LangSmith RunTree
    try:
        from langsmith.run_helpers import get_current_run_tree

        rt = get_current_run_tree()
        if rt:
            rt.add_metadata(run_meta)
            rt.add_tags(eval_tags)
    except Exception:
        pass

    config = config_for(
        thread_id,
        inputs.get("sender_email"),
        tags=eval_tags,
        metadata=run_meta,
    )
    log: list[str] = []
    clarification_asked = approval_requested = executed_before_approval = False

    start(graph, config, inputs["request"])
    for _ in range(MAX_INTERRUPTS):
        waiting = pending(graph, config)
        if waiting == "clarification":
            clarification_asked = True
            answer = inputs.get("clarification_reply")
            log.append(f"clarification asked -> {answer!r}")
            if answer is None:
                break  # the dataset has no reply for this request
            reply(graph, config, answer)
        elif waiting == "approval":
            approval_requested = True
            proposal = graph.get_state(config).values["action_proposal"]
            executed_before_approval = executed_before_approval or _executed(proposal)
            approved = inputs.get("approval_decision") == "approved"
            log.append(f"approval for {proposal.action_type.value} -> {'approve' if approved else 'reject'}")

            # Attach action_id to trace metadata for current run tree and resumption config
            config.setdefault("metadata", {})["action_id"] = proposal.action_id
            try:
                from langsmith.run_helpers import get_current_run_tree

                rt = get_current_run_tree()
                if rt:
                    rt.add_metadata({"action_id": proposal.action_id})
            except Exception:
                pass

            decide(graph, config, approved=approved)
        else:
            break

    state = graph.get_state(config).values
    proposal, policy, fields = state.get("action_proposal"), state.get("policy_result"), state.get("extracted_fields")

    if proposal and proposal.action_id:
        config.setdefault("metadata", {})["action_id"] = proposal.action_id
        try:
            from langsmith.run_helpers import get_current_run_tree

            rt = get_current_run_tree()
            if rt:
                rt.add_metadata({"action_id": proposal.action_id})
        except Exception:
            pass

    outcome: RunOutcome = {
        "fields": fields.model_dump() if fields else {},
        "clarification_asked": clarification_asked,
        "action_type": proposal.action_type.value if proposal else None,
        "citations": [{"doc_id": policy.doc_id, "effective_date": policy.effective_date}] if policy else [],
        "approval_requested": approval_requested,
        "execution_count": int(_executed(proposal)),
        "executed_before_approval": executed_before_approval,
        "action_status": proposal.status.value if proposal else None,
    }
    return outcome, log


def _langsmith_evaluator(fn):
    """Adapt an evaluator to the (run, example) arguments of langsmith 0.1.x."""

    def wrapper(run, example) -> dict:
        return fn(run.outputs, example.outputs)

    wrapper.__name__ = fn.__name__
    return wrapper


def run_langsmith_experiment() -> int:
    from langsmith import evaluate as langsmith_evaluate

    if not os.environ.get("LANGSMITH_API_KEY"):
        print("LANGSMITH_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    graph = build_graph()

    def target(inputs: dict) -> dict:
        example_id = inputs.get("example_id")
        tags = ["evaluation"]
        if example_id:
            tags.append(example_id)
        outcome, log = run_example(
            graph,
            inputs,
            example_id=example_id,
            tags=tags,
            metadata={"example_id": example_id} if example_id else {},
        )
        return dict(outcome) | {"log": log}

    results = langsmith_evaluate(
        target,
        data=dataset_name(),
        evaluators=[_langsmith_evaluator(fn) for fn in ALL_EVALUATORS],
        experiment_prefix="helpdesk-graph",
        description="src/agent graph on the 10-request evaluation dataset",
        metadata={"graph": "src.agent.graph", "tags": ["evaluation"]},
        max_concurrency=1,
    )
    print(f"Experiment: {results.experiment_name}")
    return 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="show interrupts and failures")
    parser.add_argument("--langsmith", action="store_true", help="run as a LangSmith experiment")
    args = parser.parse_args()

    if args.langsmith:
        return run_langsmith_experiment()

    graph = build_graph()
    keys = [fn.__name__ for fn in ALL_EVALUATORS]
    totals = dict.fromkeys(keys, 0)
    examples = load_examples()
    passed = 0

    print(f"{'ID':<9}{'action':<20}" + "".join(f"{k:<28}" for k in keys))
    for example in examples:
        example_id = example["metadata"]["id"]
        outcome, log = run_example(
            graph,
            example["inputs"],
            example_id=example_id,
            tags=["evaluation", example_id],
            metadata={"example_id": example_id, **example["metadata"]},
            langsmith_extra={"name": example_id, "tags": ["evaluation", example_id], "metadata": {"example_id": example_id, **example["metadata"]}},
        )
        results = evaluate(outcome, example["outputs"])
        passed += all(r["score"] for r in results)
        print(f"{example_id:<9}{str(outcome['action_type']):<20}" + "".join(
            f"{'PASS' if r['score'] else 'FAIL':<28}" for r in results
        ))
        for r in results:
            totals[r["key"]] += r["score"]
        if args.verbose:
            for line in log:
                print(f"         · {line}")
            for r in results:
                if not r["score"]:
                    print(f"         ✗ {r['key']}: {r['comment']}")

    n = len(examples)
    print(f"{'TOTAL':<29}" + "".join(f"{f'{totals[k]}/{n}':<28}" for k in keys))
    print(f"\n{passed}/{n} requests pass every evaluator")
    return 0 if passed == n else 1


if __name__ == "__main__":
    sys.exit(main())
