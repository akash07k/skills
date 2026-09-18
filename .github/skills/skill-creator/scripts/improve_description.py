#!/usr/bin/env python3
"""Improve a skill description based on eval results.

Takes eval results (from run_eval.py) and generates an improved description
using the installed Copilot CLI and its configured authentication.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from scripts.utils import parse_skill_md
from scripts.copilot_cli import copilot_command, response_text


def _description_from_response(text: str) -> str:
    match = re.search(r"<new_description>(.*?)</new_description>", text, re.DOTALL)
    description = (match.group(1) if match else text).strip()
    if len(description) >= 2 and description[0] == description[-1] and description[0] in "\"'":
        return description[1:-1]
    return description


def _call_copilot(prompt: str, model: str | None, timeout: int = 300) -> str:
    """Send the prompt over stdin with no tools available.

    Prompt goes over stdin (not argv) because it embeds the full SKILL.md
    body and can easily exceed comfortable argv length.
    """
    cmd = copilot_command(model)
    cmd.append("--no-custom-instructions")

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Copilot exited {result.returncode}\nstderr: {result.stderr}"
        )
    return response_text(result.stdout)


def improve_description(
    skill_name: str,
    skill_content: str,
    current_description: str,
    eval_results: dict,
    history: list[dict],
    model: str | None,
    log_dir: Path | None = None,
    iteration: int | None = None,
) -> str:
    """Call Copilot to improve the description based on eval results."""
    failed_triggers = [
        r for r in eval_results["results"]
        if r["should_trigger"] and not r["pass"]
    ]
    false_triggers = [
        r for r in eval_results["results"]
        if not r["should_trigger"] and not r["pass"]
    ]

    # Build scores summary
    train_score = f"{eval_results['summary']['passed']}/{eval_results['summary']['total']}"
    scores_summary = f"Train: {train_score}"

    prompt = f"""You are optimizing a skill description for a Copilot skill called "{skill_name}". A skill uses progressive disclosure: Copilot sees its name and description when deciding whether to load the SKILL.md instructions, which may link to helper scripts, references, and examples.

The description appears in Copilot's available skills. Your goal is to write a description that triggers for relevant queries and does not trigger for irrelevant ones.

Here's the current description:
<current_description>
"{current_description}"
</current_description>

Current scores ({scores_summary}):
<scores_summary>
"""
    if failed_triggers:
        prompt += "FAILED TO TRIGGER (should have triggered but didn't):\n"
        for r in failed_triggers:
            prompt += f'  - "{r["query"]}" (triggered {r["triggers"]}/{r["runs"]} times)\n'
        prompt += "\n"

    if false_triggers:
        prompt += "FALSE TRIGGERS (triggered but shouldn't have):\n"
        for r in false_triggers:
            prompt += f'  - "{r["query"]}" (triggered {r["triggers"]}/{r["runs"]} times)\n'
        prompt += "\n"

    prompt += "</scores_summary>\n\n"

    if history:
        prompt += "PREVIOUS ATTEMPTS (do NOT repeat these — try something structurally different):\n\n"
        for h in history:
            train_s = f"{h.get('train_passed', 0)}/{h.get('train_total', 0)}"
            test_s = f"{h.get('test_passed', '?')}/{h.get('test_total', '?')}" if h.get('test_passed') is not None else None
            score_str = f"train={train_s}" + (f", test={test_s}" if test_s else "")
            prompt += f'<attempt {score_str}>\n'
            prompt += f'Description: "{h["description"]}"\n'
            if h.get("train_results"):
                prompt += "Train results:\n"
                for r in h["train_results"]:
                    status = "PASS" if r["pass"] else "FAIL"
                    prompt += f'  [{status}] "{r["query"][:80]}" (triggered {r["triggers"]}/{r["runs"]})\n'
            if h.get("note"):
                prompt += f'Note: {h["note"]}\n'
            prompt += "</attempt>\n\n"

    prompt += f"""Skill content (for context on what the skill does):
<skill_content>
{skill_content}
</skill_content>

Based on the failures, write a new and improved description that is more likely to trigger correctly. When I say "based on the failures", it's a bit of a tricky line to walk because we don't want to overfit to the specific cases you're seeing. So what I DON'T want you to do is produce an ever-expanding list of specific queries that this skill should or shouldn't trigger for. Instead, try to generalize from the failures to broader categories of user intent and situations where this skill would be useful or not useful. The reason for this is twofold:

1. Avoid overfitting
2. The list might get loooong and it's injected into ALL queries and there might be a lot of skills, so we don't want to blow too much space on any given description.

Concretely, your description should not be more than about 100-200 words, even if that comes at the cost of accuracy. There is a hard limit of 1024 characters — descriptions over that will be truncated, so stay comfortably under it.
The description must not contain the angle-bracket characters < or > because the skill validator rejects them.
Prefer text that is safe when pasted as an unquoted YAML scalar: avoid a colon followed by a space, a trailing colon, YAML indicator characters at the start, or a space followed by #. This is a preference rather than a hard constraint because the documented application format uses a YAML block scalar.

Here are some tips that we've found to work well in writing these descriptions:
- The skill should be phrased in the imperative -- "Use this skill for" rather than "this skill does"
- The skill description should focus on the user's intent, what they are trying to achieve, vs. the implementation details of how the skill works.
- The description competes with other skills for Copilot's attention — make it distinctive and immediately recognizable.
- If you're getting lots of failures after repeated attempts, change things up. Try different sentence structures or wordings.

I'd encourage you to be creative and mix up the style in different iterations since you'll have multiple opportunities to try different approaches and we'll just grab the highest-scoring one at the end.

Please respond with only the new description text in <new_description> tags, nothing else."""

    text = _call_copilot(prompt, model)

    description = _description_from_response(text)

    transcript: dict = {
        "iteration": iteration,
        "prompt": prompt,
        "response": text,
    }

    def save_transcript() -> None:
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"improve_iter_{iteration or 'unknown'}.json"
            log_file.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

    if not description.strip():
        save_transcript()
        raise RuntimeError("Copilot returned an empty skill description")

    invalid_reasons = []
    if len(description) > 1024:
        invalid_reasons.append(
            f"at {len(description)} characters it exceeds the 1024-character hard limit"
        )
    if "<" in description or ">" in description:
        invalid_reasons.append("it contains the forbidden angle-bracket characters < or >")
    # Retry once for hard constraints. Plain-scalar safety is only a prompt
    # preference because the documented application format uses a block scalar.
    if invalid_reasons:
        shorten_prompt = (
            f"{prompt}\n\n"
            f"---\n\n"
            f"A previous attempt produced this invalid description; "
            f"{' and '.join(invalid_reasons)}:\n\n"
            f'"{description}"\n\n'
            f"Rewrite it to be nonempty, at most 1024 characters, and free of "
            f"angle brackets and YAML plain-scalar hazards while keeping the "
            f"most important trigger words and intent coverage. Respond with only "
            f"the new description in <new_description> tags."
        )
        transcript["rewrite_prompt"] = shorten_prompt
        save_transcript()
        shorten_text = _call_copilot(shorten_prompt, model)
        description = _description_from_response(shorten_text)

        transcript["rewrite_response"] = shorten_text
        save_transcript()

    if not description.strip():
        raise RuntimeError("Copilot returned an empty skill description")
    if len(description) > 1024:
        raise RuntimeError("Copilot's rewritten description still exceeds 1024 characters")
    if "<" in description or ">" in description:
        raise RuntimeError("Copilot's rewritten description still contains angle brackets")
    transcript["final_description"] = description
    save_transcript()

    return description


def main():
    parser = argparse.ArgumentParser(description="Improve a skill description based on eval results")
    parser.add_argument("--eval-results", required=True, help="Path to eval results JSON (from run_eval.py)")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--history", default=None, help="Path to history JSON (previous attempts)")
    parser.add_argument("--model", default=None, help="Copilot model ID (default: user's configured Copilot model)")
    parser.add_argument("--verbose", action="store_true", help="Print thinking to stderr")
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    eval_results = json.loads(Path(args.eval_results).read_text(encoding="utf-8"))
    history = []
    if args.history:
        history = json.loads(Path(args.history).read_text(encoding="utf-8"))

    name, _, content = parse_skill_md(skill_path)
    current_description = eval_results["description"]

    if args.verbose:
        print(f"Current: {current_description}", file=sys.stderr)
        print(f"Score: {eval_results['summary']['passed']}/{eval_results['summary']['total']}", file=sys.stderr)

    new_description = improve_description(
        skill_name=name,
        skill_content=content,
        current_description=current_description,
        eval_results=eval_results,
        history=history,
        model=args.model,
    )

    if args.verbose:
        print(f"Improved: {new_description}", file=sys.stderr)

    # Output as JSON with both the new description and updated history
    output = {
        "description": new_description,
        "history": history + [{
            "description": current_description,
            "train_passed": eval_results["summary"]["passed"],
            "train_total": eval_results["summary"]["total"],
            "train_results": eval_results["results"],
        }],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
