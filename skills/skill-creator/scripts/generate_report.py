#!/usr/bin/env python3
"""Generate an HTML report from run_loop.py output.

Takes the JSON output from run_loop.py and generates a visual HTML report
showing each description attempt with text pass/fail results for each test case.
Distinguishes between train and test queries.
"""

import argparse
import html
import json
import sys
from pathlib import Path

from scripts.utils import aggregate_runs, best_iteration


def index_results(results: list[dict] | None) -> dict:
    """Index results by stable evaluation ID."""
    return {result["eval_id"]: result for result in results or []}

def score_class(correct: int, total: int) -> str:
    """Return the report class for a run score."""
    if total > 0:
        ratio = correct / total
        if ratio >= 0.8:
            return "score-good"
        if ratio >= 0.5:
            return "score-ok"
    return "score-bad"


def generate_html(data: dict, auto_refresh: bool = False, skill_name: str = "") -> str:
    """Generate an accessible report; live reports offer opt-in, pausable refresh."""
    history = data.get("history", [])
    title_prefix = html.escape(skill_name + " \u2014 ") if skill_name else ""

    # Keep each occurrence: identical query text can represent different cases.
    train_queries: list[dict] = []
    test_queries: list[dict] = []
    if history:
        for key, r in index_results(history[0].get("train_results", [])).items():
            train_queries.append({"key": key, "query": r["query"], "should_trigger": r.get("should_trigger", True)})
        for key, r in index_results(history[0].get("test_results", [])).items():
            test_queries.append({"key": key, "query": r["query"], "should_trigger": r.get("should_trigger", True)})

    html_parts = ["""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>""" + title_prefix + """Skill Description Optimization</title>
    <style>
        body {
            font-family: 'Lora', Georgia, serif;
            max-width: 100%;
            margin: 0 auto;
            padding: 20px;
            background: #faf9f5;
            color: #141413;
        }
        h1, h2 { font-family: 'Poppins', sans-serif; color: #141413; }
        h2 { font-size: 1.2rem; }
        .explainer {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
            color: #65645d;
            font-size: 0.875rem;
            line-height: 1.6;
        }
        .summary {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
        }
        .summary p { margin: 5px 0; }
        .best { color: #4d6135; font-weight: bold; }
        .table-container {
            overflow-x: auto;
            width: 100%;
        }
        table {
            border-collapse: collapse;
            background: white;
            border: 1px solid #e8e6dc;
            border-radius: 6px;
            font-size: 12px;
            min-width: 100%;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border: 1px solid #e8e6dc;
            white-space: normal;
            word-wrap: break-word;
        }
        th {
            font-family: 'Poppins', sans-serif;
            background: #141413;
            color: #faf9f5;
            font-weight: 500;
        }
        th.test-col {
            background: #326a9f;
        }
        th[scope="row"] { background: #faf9f5; color: #141413; }
        .best-row th[scope="row"] { background: #eef2e8; }
        .query-kind { display: block; margin-bottom: 0.5rem; }
        caption { text-align: left; font-size: 1rem; padding: 0.75rem 0; }
        th.query-col { min-width: 200px; }
        td.description {
            font-family: monospace;
            font-size: 0.875rem;
            word-wrap: break-word;
            max-width: 400px;
        }
        td.result {
            text-align: center;
            font-size: 16px;
            min-width: 40px;
        }
        td.test-result {
            background: #f0f6fc;
        }
        .pass { color: #4d6135; }
        .fail, .error { color: #a12828; }
        .rate {
            font-size: 0.75rem;
            color: #65645d;
            display: block;
        }
        tr:hover { background: #faf9f5; }
        .score {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 11px;
        }
        .score-good { background: #eef2e8; color: #4d6135; }
        .score-ok { background: #fef3c7; color: #855000; }
        .score-bad { background: #fceaea; color: #a12828; }
        .best-row { background: #f5f8f2; }
        th.positive-col { border-bottom: 3px solid #4d6135; }
        th.negative-col { border-bottom: 3px solid #a12828; }
        th.test-col.positive-col { border-bottom: 3px solid #4d6135; }
        th.test-col.negative-col { border-bottom: 3px solid #a12828; }
        .legend { font-family: 'Poppins', sans-serif; display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 10px; font-size: 13px; align-items: center; }
        .legend-item { display: flex; align-items: center; gap: 6px; }
        .legend-swatch { width: 16px; height: 16px; border-radius: 3px; display: inline-block; }
        .swatch-positive { background: #141413; border-bottom: 3px solid #4d6135; }
        .swatch-negative { background: #141413; border-bottom: 3px solid #a12828; }
        .swatch-test { background: #326a9f; }
        .swatch-train { background: #141413; }
        :focus-visible { outline: 3px solid #205b91; outline-offset: 3px; }
        button, summary { cursor: pointer; }
        button { padding: 0.5rem 1rem; font: inherit; }
        summary { font-family: 'Poppins', sans-serif; }
        details p { white-space: pre-wrap; }
        .refresh-controls { padding: 1rem; border: 1px solid #e8e6dc; margin-bottom: 1rem; }
        .refresh-controls label { display: inline-flex; gap: 0.5rem; align-items: center; margin: 0.75rem; }
        .refresh-controls input { width: 20px; height: 20px; }
        .skip-link { position: absolute; top: -10rem; left: 20px; padding: 0.75rem; background: white; color: #205b91; }
        .skip-link:focus { top: 0.5rem; }
    </style>
</head>
<body>
    <a class="skip-link" href="#main-content">Skip to optimization report</a>
    <main id="main-content" tabindex="-1">
    <h1>""" + title_prefix + """Skill Description Optimization</h1>
    <div class="explainer">
        <strong>Optimizing your skill's description.</strong> Each row is an iteration: a new description attempt. Each query result says Pass if the skill triggered correctly (or correctly did not trigger), or Fail if it got it wrong. The summary's best query score counts queries that meet the evaluator's pass threshold. Train and Test run scores in the iteration table count correct individual runs across retries. Query headers state both the dataset and whether the skill should trigger.
        Description cells expand to show the full text.
    </div>
"""]

    if auto_refresh:
        html_parts.append("""
    <section class="refresh-controls" aria-labelledby="refresh-heading">
        <h2 id="refresh-heading">Live report updates</h2>
        <p id="refresh-help">Automatic refresh is off by default to preserve your reading position. When enabled, it runs every five seconds, but pauses while refresh controls or the results table have focus, a description is expanded, or this browser tab is hidden. Screen-reader browse-mode reading cannot be detected, so leave automatic refresh off while reading in browse mode.</p>
        <button type="button" id="refresh-report">Refresh report</button>
        <label for="auto-refresh"><input type="checkbox" id="auto-refresh" aria-describedby="refresh-help">Automatically refresh every five seconds</label>
        <p id="refresh-status" role="status"></p>
        <p id="refresh-error" class="error" role="alert"></p>
        <noscript><p>JavaScript is unavailable. Use your browser's Reload command to update this report.</p></noscript>
    </section>
""")

    # Summary section
    test_size = data.get("test_size")
    has_holdout = bool(test_queries) or (test_size or 0) > 0
    exit_reason = data.get("exit_reason")
    error = data.get("error")
    html_parts.append(f"""
    <section class="summary" aria-labelledby="summary-heading">
        <h2 id="summary-heading">Optimization summary</h2>
        <p><strong>Original:</strong> {html.escape(data.get('original_description', 'N/A'))}</p>
        <p class="best"><strong>Best:</strong> {html.escape(data.get('best_description', 'N/A'))}</p>
        <p><strong>Best query score:</strong> {html.escape(str(data.get('best_score', 'N/A')))} queries passed {'(held-out test set)' if has_holdout else '(training set)'}</p>
        {'<p><strong>Interpretation:</strong> The best test score is the maximum used to select among attempted descriptions, so it is an optimistically biased model-selection estimate rather than an untouched final validation score.</p>' if has_holdout else ''}
        <p><strong>Iterations:</strong> {html.escape(str(data.get('iterations_run', 0)))} | <strong>Train queries:</strong> {html.escape(str(data.get('train_size', '?')))} | <strong>Test queries:</strong> {html.escape(str(test_size if test_size is not None else '?'))}</p>
        {f'<p><strong>Exit reason:</strong> {html.escape(str(exit_reason))}</p>' if exit_reason else ''}
        {f'<p class="error" role="alert"><strong>Run failed:</strong> {html.escape(str(error))}</p>' if error else ''}
    </section>
""")

    # Legend
    html_parts.append("""
    <div class="legend">
        <span style="font-weight:600">Query columns:</span>
        <span class="legend-item"><span class="legend-swatch swatch-positive" aria-hidden="true"></span> Should trigger</span>
        <span class="legend-item"><span class="legend-swatch swatch-negative" aria-hidden="true"></span> Should NOT trigger</span>
        <span class="legend-item"><span class="legend-swatch swatch-train" aria-hidden="true"></span> Train</span>
        <span class="legend-item"><span class="legend-swatch swatch-test" aria-hidden="true"></span> Test</span>
    </div>
""")

    # Table header
    html_parts.append("""
    <h2 id="results-heading">Results by iteration</h2>
    <div class="table-container" tabindex="0" role="region" aria-labelledby="results-heading">
    <table>
        <caption>Train and test results for each description attempt</caption>
        <thead>
            <tr>
                <th scope="col">Iteration</th>
                <th scope="col">Train correct runs</th>
                <th scope="col">Test correct runs</th>
                <th scope="col" class="query-col">Description</th>
""")

    # Add column headers for train queries
    for index, qinfo in enumerate(train_queries, 1):
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        expected = "Should trigger" if qinfo["should_trigger"] else "Should not trigger"
        html_parts.append(f'                <th scope="col" class="{polarity}"><span class="query-kind">Train query {index}: {expected}</span>{html.escape(qinfo["query"])}</th>\n')

    # Add column headers for test queries (different color)
    for index, qinfo in enumerate(test_queries, 1):
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        expected = "Should trigger" if qinfo["should_trigger"] else "Should not trigger"
        html_parts.append(f'                <th scope="col" class="test-col {polarity}"><span class="query-kind">Test query {index}: {expected}</span>{html.escape(qinfo["query"])}</th>\n')

    html_parts.append("""            </tr>
        </thead>
        <tbody>
""")

    # Find best iteration for highlighting
    if not history:
        best_iter = None
        html_parts.append('            <tr><td colspan="4">No evaluation results yet. Refresh a live report after an iteration completes.</td></tr>\n')
    else:
        best_iter = best_iteration(history, has_holdout).get("iteration")

    # Add rows for each iteration
    for h in history:
        iteration = h.get("iteration", "?")
        iteration_text = html.escape(str(iteration))
        description = h.get("description", "")
        train_results = h.get("train_results", []) or []
        test_results = h.get("test_results", []) or []

        train_by_query = index_results(train_results)
        test_by_query = index_results(test_results)

        train_correct, train_runs = aggregate_runs(train_results)
        test_correct, test_runs = aggregate_runs(test_results)

        train_class = score_class(train_correct, train_runs)
        test_class = score_class(test_correct, test_runs)

        row_class = "best-row" if iteration == best_iter else ""

        train_score = f"{train_correct} / {train_runs} correct" if train_runs else "Not evaluated"
        test_score = f"{test_correct} / {test_runs} correct" if test_runs else "Not evaluated"
        html_parts.append(f"""            <tr class="{row_class}">
                <th scope="row">Iteration {iteration_text}{' (Best)' if iteration == best_iter else ''}</th>
                <td><span class="score {train_class}">{train_score}</span></td>
                <td><span class="score {test_class}">{test_score}</span></td>
                <td class="description"><details><summary>Description for iteration {iteration_text}</summary><p>{html.escape(description) if description else 'No description available.'}</p></details></td>
""")

        for queries, results, dataset_class in [
            (train_queries, train_by_query, ""),
            (test_queries, test_by_query, "test-result"),
        ]:
            for qinfo in queries:
                r = results.get(qinfo["key"], {})
                triggers = r.get("triggers", 0)
                runs = r.get("runs", 0)
                outcome = "Pass" if r.get("pass", False) else "Fail"
                css_class = "pass" if r.get("pass", False) else "fail"
                rate = f"Triggered {triggers} of {runs} runs"
                if not r or not runs:
                    outcome, css_class = "Not evaluated", ""
                if r.get("error"):
                    outcome, css_class = "Error", "fail"
                    rate = str(r["error"])

                html_parts.append(f'                <td class="result {dataset_class} {css_class}">{outcome}<span class="rate">{html.escape(rate)}</span></td>\n')

        html_parts.append("            </tr>\n")

    html_parts.append("""        </tbody>
    </table>
    </div>
""")

    if auto_refresh:
        html_parts.append("""
    <script>
        const refresh = document.getElementById('auto-refresh');
        const preferenceKey = 'skill-report-auto-refresh:' + location.pathname;
        const status = document.getElementById('refresh-status');
        const error = document.getElementById('refresh-error');
        document.getElementById('refresh-report').addEventListener('click', () => location.reload());
        try {
            refresh.checked = sessionStorage.getItem(preferenceKey) === 'true';
        } catch (err) {
            refresh.disabled = true;
            error.textContent = 'Automatic refresh is unavailable because this browser blocked session storage. Use Refresh report instead.';
        }
        refresh.addEventListener('change', () => {
            try {
                sessionStorage.setItem(preferenceKey, String(refresh.checked));
                status.textContent = refresh.checked ? 'Automatic refresh enabled. Updates pause while refresh controls or the results table have focus, or a description is expanded.' : 'Automatic refresh off. Use Refresh report to update.';
            } catch (err) {
                refresh.checked = false;
                error.textContent = 'Could not save the automatic refresh setting. Use Refresh report instead.';
            }
        });
        setInterval(() => {
            const interactionHasFocus = document.querySelector('.refresh-controls :focus, .table-container:focus-within') !== null;
            if (refresh.checked && !document.hidden && !interactionHasFocus && !document.querySelector('details[open]')) {
                location.reload();
            }
        }, 5000);
    </script>
""")

    html_parts.append("""
    </main>
</body>
</html>
""")

    return "".join(html_parts)


def main():
    parser = argparse.ArgumentParser(description="Generate HTML report from run_loop output")
    parser.add_argument("input", help="Path to JSON output from run_loop.py (or - for stdin)")
    parser.add_argument("-o", "--output", default=None, help="Output HTML file (default: stdout)")
    parser.add_argument("--skill-name", default="", help="Skill name to include in the report title")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    html_output = generate_html(data, skill_name=args.skill_name)

    if args.output:
        Path(args.output).write_text(html_output, encoding="utf-8")
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(html_output)


if __name__ == "__main__":
    main()
