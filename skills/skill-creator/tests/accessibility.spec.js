const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { spawn, execFileSync } = require("node:child_process");
const { mkdtempSync, readFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

let root;
let server;
let baseURL;
const PYTHON = process.env.PYTHON || "python";

function pythonLaunchError(error) {
  if (error.code !== "ENOENT" && error.code !== "EINVAL") return error;
  return new Error(
    `Could not launch Python with ${JSON.stringify(PYTHON)}. ` +
    "Set PYTHON to a Python executable path; on PowerShell, for example: " +
    "$env:PYTHON='C:\\path\\to\\python.exe'. WindowsApps aliases and .cmd shims may not launch here."
  );
}

test.beforeAll(async () => {
  root = mkdtempSync(path.join(tmpdir(), "skill-review-test-"));
  const fixture = path.join(__dirname, "review_fixture.py");
  try {
    execFileSync(PYTHON, [fixture, root], { stdio: "pipe" });
  } catch (error) {
    throw pythonLaunchError(error);
  }
  server = spawn(PYTHON, ["-u", fixture, root, "--serve"], { stdio: ["ignore", "pipe", "pipe"] });
  baseURL = await new Promise((resolve, reject) => {
    let output = "";
    server.on("error", error => reject(pythonLaunchError(error)));
    server.stderr.on("data", data => process.stderr.write(data));
    server.on("exit", code => reject(new Error("Fixture server exited: " + code)));
    server.stdout.on("data", data => {
      output += data;
      if (output.includes("\n")) resolve(JSON.parse(output.split("\n")[0]).url);
    });
  });
});

test.afterAll(async () => {
  if (server && server.exitCode === null) {
    const stopped = new Promise(resolve => server.once("exit", resolve));
    server.kill();
    await stopped;
  }
  if (root) rmSync(root, { recursive: true, force: true });
});

test.beforeEach(async ({ page }) => {
  // UI semantics and feedback do not depend on external fonts or spreadsheet scripts.
  await page.route(/^https:\/\//, route => route.abort());
});

async function openFile(page, name) {
  await page.goto(pathToFileURL(path.join(root, name)).href);
}

async function checkAccessibility(page) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"])
    .analyze();
  expect(result.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.html) }))).toEqual([]);
}

test("viewer supports named controls, local tabs, disclosures and run-heading focus", async ({ page }) => {
  const sheetRequests = [];
  page.on("request", request => {
    if (request.url().includes("sheetjs")) sheetRequests.push(request.url());
  });
  await openFile(page, "static.html");
  const heading = page.locator("#run-heading");
  await expect(heading).toHaveText(/Run 1 of 2/);
  await expect(page.getByRole("textbox", { name: "Your Feedback" })).toBeEnabled();
  await expect(page.getByRole("link", { name: "Download answer.txt", exact: true })).toBeVisible();
  await expect(page.locator("#outputs-body")).toContainText("</script>");
  await checkAccessibility(page);
  const grades = page.getByRole("button", { name: "Formal Grades" });
  await grades.focus();
  await page.keyboard.press("Space");
  await expect(grades).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#grades-content")).toContainText("Fail: Has all rows");
  await expect(grades).toBeFocused();
  const previous = page.getByRole("button", { name: "Previous Output" });
  await previous.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("link", { name: "Download previous old.txt" })).toBeVisible();
  await checkAccessibility(page);
  await heading.focus();
  await page.keyboard.press("ArrowRight");
  await expect(heading).toHaveText(/Run 1 of 2/);
  await page.getByRole("button", { name: "Next", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(heading).toBeFocused();
  await expect(heading).toHaveText(/Run 2 of 2/);
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await page.getByRole("tab", { name: "Outputs" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Benchmark" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Benchmark" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("textbox", { name: "Your Feedback" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: /assertion results and evidence/ })).toContainText("Run 1: Fail");
  await expect(page.getByRole("table", { name: /assertion results and evidence/ })).toContainText("The last row is missing.");
  await expect(page.getByRole("row", { name: /Time \(seconds\).*1\.0s/ }).locator("td").last()).toHaveClass(/benchmark-delta-negative/);
  await expect(page.getByRole("row", { name: /Pass Rate.*\+0%/ })).toBeVisible();
  expect(sheetRequests).toEqual([]);
  await expect(page.getByRole("row", { name: /Tokens.*\+4/ }).locator("td").last()).toHaveClass(/benchmark-delta-negative/);
  await expect(page.getByRole("columnheader", { name: "Errors During Execution" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Crashes During Execution" })).toHaveCount(0);
  await checkAccessibility(page);
  await page.keyboard.press("Home");
  await expect(page.getByRole("tab", { name: "Outputs" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("tabpanel", { name: "Outputs" })).toBeFocused();
});

test("formal grades treat model data as text and tolerate malformed expectations", async ({ page }) => {
  await openFile(page, "hostile-grades.html");
  await page.getByRole("button", { name: "Formal Grades" }).press("Enter");
  await expect(page.locator("#grades-content")).toContainText("? passed, ? failed of ?");
  await expect(page.locator("#grades-content img")).toHaveCount(0);
  await expect(page.locator("body")).not.toHaveAttribute("data-injected", "yes");
  await expect(page.getByRole("textbox", { name: "Your Feedback" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Submit All Reviews" })).toBeEnabled();
  await checkAccessibility(page);
});

test("benchmark render failures remain announced after live initialization", async ({ page }) => {
  const body = readFileSync(path.join(root, "benchmark-error.html"), "utf8");
  await page.route("**/?benchmark-error", route => route.fulfill({ contentType: "text/html", body }));
  await page.goto(baseURL + "/?benchmark-error");
  await expect(page.getByRole("alert")).toContainText("Benchmark data could not be rendered");
  await expect(page.locator("#benchmark-content")).toHaveText("Benchmark data could not be rendered.");
  await checkAccessibility(page);
});

test("static submit downloads correct feedback and uses a native keyboard dialog", async ({ page }) => {
  await openFile(page, "static.html");
  await page.getByRole("textbox", { name: "Your Feedback" }).fill("First feedback");
  await page.getByRole("button", { name: "Next", exact: true }).press("Enter");
  await page.getByRole("textbox", { name: "Your Feedback" }).fill("Second feedback");
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Submit All Reviews" }).press("Enter");
  const download = await downloaded;
  const payload = JSON.parse(readFileSync(await download.path(), "utf8"));
  expect(payload.status).toBe("complete");
  expect(payload.reviews.map(r => r.feedback)).toEqual(["First feedback", "Second feedback"]);
  const dialog = page.getByRole("dialog", { name: "Feedback download requested" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Return to reviews" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Return to reviews" })).toBeFocused();
  await checkAccessibility(page);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Submit All Reviews" })).toBeFocused();
});

test("feedback status waits for a pause before announcing storage", async ({ page }) => {
  await openFile(page, "static.html");
  const feedback = page.getByRole("textbox", { name: "Your Feedback" });
  const status = page.locator("#feedback-status");
  await feedback.fill("A draft review");
  await expect(status).toHaveText("");
  await page.waitForTimeout(1100);
  await expect(status).toHaveText("Stored in this page only. Submit to download feedback.json.");
});

test("live feedback serializes autosave and completion, reloads with previous iteration, and exposes failures", async ({ page }) => {
  await page.goto(baseURL);
  const feedback = page.getByRole("textbox", { name: "Your Feedback" });
  await expect(feedback).toBeEnabled();
  const statuses = [];
  let started;
  let completionStarted;
  const firstSave = new Promise(resolve => { started = resolve; });
  const completionSave = new Promise(resolve => { completionStarted = resolve; });
  await page.route("**/api/feedback", async route => {
    if (route.request().method() === "POST") {
      statuses.push(route.request().postDataJSON().status);
      if (statuses.length === 1) {
        started();
        await new Promise(resolve => setTimeout(resolve, 300));
      } else if (statuses.length === 2) {
        completionStarted();
        await new Promise(resolve => setTimeout(resolve, 300));
      }
    }
    await route.continue();
  });
  await feedback.fill("Saved current iteration");
  await firstSave;
  const submit = page.getByRole("button", { name: "Submit All Reviews" });
  await submit.press("Enter");
  await completionSave;
  await expect(submit).toBeEnabled();
  await expect(submit).toBeFocused();
  await expect(page.getByRole("dialog", { name: "Review complete", exact: true })).toBeVisible();
  expect(statuses).toEqual(["in_progress", "complete"]);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Next", exact: true }).press("Enter");
  // Wait past the one-second debounce: no pending save may revert completion.
  await page.waitForTimeout(1200);
  expect(statuses).toEqual(["in_progress", "complete"]);
  expect(JSON.parse(readFileSync(path.join(root, "workspace", "feedback.json"), "utf8")).status).toBe("complete");
  await page.reload();
  await expect(feedback).toHaveValue("Saved current iteration");
  await page.route("**/api/feedback", route => {
    if (route.request().method() === "POST") return route.fulfill({ status: 500, json: { error: "Disk full" } });
    return route.continue();
  });
  await feedback.fill("Unsaved changes");
  await page.getByRole("button", { name: "Submit All Reviews" }).press("Enter");
  await expect(page.getByRole("alert")).toContainText("Feedback was not saved");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Download feedback backup" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit All Reviews" })).toBeFocused();
  await checkAccessibility(page);
});

test("live autosave preserves orphan feedback", async ({ page }) => {
  let posted;
  await page.route("**/api/feedback", route => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        json: { reviews: [{ run_id: "removed-run", feedback: "Keep this review" }] },
      });
    }
    posted = route.request().postDataJSON();
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto(baseURL);
  await page.getByRole("textbox", { name: "Your Feedback" }).fill("Current review");
  await expect.poll(() => posted).not.toBeUndefined();
  expect(posted.reviews).toEqual(expect.arrayContaining([
    expect.objectContaining({ run_id: "removed-run", feedback: "Keep this review" }),
  ]));
});

test("live feedback flushes on page hide", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.sendBeacon = (url, body) => {
      window.testBeacon = { url };
      body.text().then(text => { window.testBeacon.body = text; });
      return true;
    };
  });
  await page.route("**/api/feedback", route => {
    if (route.request().method() === "GET") {
      return route.fulfill({ json: { reviews: [] } });
    }
    return new Promise(resolve => setTimeout(resolve, 500))
      .then(() => route.fulfill({ json: { ok: true } }));
  });
  await page.goto(baseURL);
  await page.getByRole("textbox", { name: "Your Feedback" }).fill("Flush before leaving");
  await page.evaluate(() => { saveCurrentFeedback(); });
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  await expect.poll(() => page.evaluate(() => window.testBeacon?.body)).not.toBeUndefined();
  const beacon = await page.evaluate(() => ({
    url: window.testBeacon.url,
    body: JSON.parse(window.testBeacon.body),
  }));
  expect(beacon.url).toBe("/api/feedback");
  expect(beacon.body.reviews).toEqual(expect.arrayContaining([
    expect.objectContaining({ feedback: "Flush before leaving" }),
  ]));
});

test("failed feedback load is announced and cannot overwrite saved feedback", async ({ page }) => {
  await page.route("**/api/feedback", route => route.fulfill({ status: 500, json: { error: "Cannot read feedback" } }));
  await page.goto(baseURL);
  await expect(page.getByRole("alert")).toContainText("Saved feedback could not be loaded");
  await expect(page.getByRole("textbox", { name: "Your Feedback" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Submit All Reviews" })).toBeDisabled();
  await checkAccessibility(page);
});

test("query editor preserves keyboard focus, labels, sorting and export contract", async ({ page }) => {
  await openFile(page, "editor.html");
  await checkAccessibility(page);
  await expect(page.locator("#trigger-heading")).toHaveAttribute("aria-sort", "none");
  await expect(page.locator("#eval-body > tr").first()).toHaveAttribute("id", "row-1");
  const checkbox = page.getByRole("checkbox", { name: "Should trigger query 1", exact: true });
  await checkbox.focus();
  await page.keyboard.press("Space");
  await expect(checkbox).not.toBeChecked();
  await expect(checkbox).toBeFocused();
  await page.getByRole("button", { name: /Add Query/ }).press("Enter");
  const query3 = page.getByRole("textbox", { name: "Query 3", exact: true });
  await expect(query3).toBeFocused();
  await query3.fill("New query");
  const sort = page.locator("#sort-trigger");
  await sort.press("Enter");
  await expect(sort).toBeFocused();
  await expect(page.locator("#trigger-heading")).toHaveAttribute("aria-sort", "descending");
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export Eval Set" }).press("Enter");
  const payload = JSON.parse(readFileSync(await (await downloaded).path(), "utf8"));
  expect(payload).toEqual([
    { query: "New query", should_trigger: true },
    { query: '</script><img src=x onerror="document.body.dataset.injected=\'yes\'">', should_trigger: false },
    { query: '</script><img src=x onerror="document.body.dataset.injected=\'yes\'">', should_trigger: false },
  ]);
  await page.getByRole("button", { name: "Delete query 3", exact: true }).press("Enter");
  await expect(page.getByRole("textbox", { name: "Query 1", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Delete query 1", exact: true }).press("Enter");
  await page.getByRole("button", { name: "Delete query 2", exact: true }).press("Enter");
  await expect(page.getByRole("button", { name: /Add Query/ })).toBeFocused();
  await page.getByRole("button", { name: "Export Eval Set" }).press("Enter");
  await expect(page.getByRole("alert")).toContainText("Nothing to export");
  await checkAccessibility(page);
});

test("query editor keeps query text outside row headers and restores authored order", async ({ page }) => {
  await openFile(page, "editor.html");
  const query = page.getByRole("textbox", { name: "Query 1", exact: true });
  await expect(query).toHaveValue('</script><img src=x onerror="document.body.dataset.injected=\'yes\'">');
  await expect(page.locator("#eval-body img")).toHaveCount(0);
  await expect(page.locator("body")).not.toHaveAttribute("data-injected");
  await expect(query.locator("xpath=ancestor::th")).toHaveCount(0);
  await expect(page.getByRole("rowheader", { name: "Query 1", exact: true })).toBeVisible();
  const sort = page.locator("#sort-trigger");
  await sort.press("Enter");
  await sort.press("Enter");
  await sort.press("Enter");
  await expect(page.locator("#trigger-heading")).toHaveAttribute("aria-sort", "none");
  await expect(page.locator("#eval-body > tr").first()).toHaveAttribute("id", "row-1");
  await expect(sort).toHaveText("Sort: Yes first");
  await expect(page.getByRole("status")).toHaveText("Restored authored query order.");
  await checkAccessibility(page);
});

test("feedback backup includes every run and remains in progress", async ({ page }) => {
  await openFile(page, "static.html");
  await page.getByRole("textbox", { name: "Your Feedback" }).fill("Draft");
  const downloaded = page.waitForEvent("download");
  await page.evaluate(() => downloadFeedback(false));
  const payload = JSON.parse(readFileSync(await (await downloaded).path(), "utf8"));
  expect(payload.status).toBe("in_progress");
  expect(payload.reviews).toHaveLength(2);
  expect(payload.reviews[1].feedback).toBe("");
});

test("optimization report has native descriptions, textual duplicate results and opt-in refresh", async ({ page }) => {
  await openFile(page, "report.html");
  await checkAccessibility(page);
  await expect(page.getByRole("checkbox", { name: /Automatically refresh/ })).not.toBeChecked();
  const description = page.locator("summary").first();
  await description.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("A full description.", { exact: true })).toBeVisible();
  await expect(page.locator("td.result").nth(0)).toContainText("Pass");
  await expect(page.locator("td.result").nth(1)).toContainText("Fail");
  await expect(page.locator("meta[http-equiv='refresh']")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect(description).toBeFocused();
  expect(await page.evaluate(() => document.querySelector(".table-container:focus-within") !== null)).toBe(true);
});

test("single-configuration benchmark does not invent a baseline or delta", async ({ page }) => {
  await openFile(page, "single.html");
  await page.getByRole("tab", { name: "Benchmark" }).press("Enter");
  const summary = page.getByRole("table", { name: "Summary: mean and standard deviation." });
  await expect(summary.getByRole("columnheader")).toHaveText(["Metric", "With Skill"]);
  await expect(summary).not.toContainText("Delta");
  await expect(summary).not.toContainText("Config B");
  await checkAccessibility(page);
});

test("benchmark configuration metadata is rendered as text", async ({ page }) => {
  await openFile(page, "escaped.html");
  await page.getByRole("tab", { name: "Benchmark" }).press("Enter");
  await expect(page.locator("#benchmark-content img")).toHaveCount(0);
  await expect(page.locator("body")).not.toHaveAttribute("data-injected");
  await expect(page.locator("#benchmark-content")).toContainText("<img src=x");
});

test("malformed benchmark measurements remain available and are not reported as zero", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await openFile(page, "malformed-benchmark.html");
  await page.getByRole("tab", { name: "Benchmark" }).press("Enter");
  await expect(page.locator("#benchmark-content")).toContainText("Not available");
  await expect(page.locator("#benchmark-content")).not.toContainText("NaN");
  await expect(page.getByRole("alert")).toHaveText("");
  expect(pageErrors).toEqual([]);
  await checkAccessibility(page);
});

test("benchmark summary includes every configuration", async ({ page }) => {
  await openFile(page, "three.html");
  await page.getByRole("tab", { name: "Benchmark" }).press("Enter");
  const summary = page.getByRole("table", { name: /Summary: mean and standard deviation/ });
  await expect(summary.getByRole("columnheader")).toHaveText([
    "Metric", "With Skill", "Old Skill", "Without Skill", "Delta",
  ]);
  await expect(summary).toContainText("40%");
  await checkAccessibility(page);
});

test("empty viewer does not throw or expose enabled review actions", async ({ page }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await openFile(page, "empty.html");
  await expect(page.getByRole("heading", { name: "No evaluation runs available" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit All Reviews" })).toBeDisabled();
  await checkAccessibility(page);
  expect(errors).toEqual([]);
});

test("file previews retain names and downloads, and spreadsheets expose coordinate headers", async ({ page }) => {
  // Stub only the existing external parser: this test covers our generated table semantics.
  await page.addInitScript(() => {
    window.XLSX = {
      read: () => ({
        SheetNames: ["Data", "Empty"],
        Sheets: { Data: { "!ref": "A1:B2", A1: { v: "Name" }, B1: { v: "Value" }, A2: { v: "Example" }, B2: { v: "10" } }, Empty: {} },
      }),
      utils: {
        decode_range: () => ({ s: { r: 0, c: 0 }, e: { r: 1, c: 1 } }),
        encode_col: col => String.fromCharCode(65 + col),
        encode_cell: ({ r, c }) => String.fromCharCode(65 + c) + (r + 1),
        format_cell: cell => cell.v,
      },
    };
  });
  await openFile(page, "media.html");
  await expect(page.getByRole("img", { name: "image.svg", exact: true })).toBeVisible();
  const table = page.getByRole("table", { name: /data.xlsx, sheet Data/ });
  await expect(table.getByRole("columnheader", { name: "A", exact: true })).toBeVisible();
  await expect(table.getByRole("rowheader", { name: "2", exact: true })).toBeVisible();
  await expect(table.getByRole("cell", { name: "Example", exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: /Empty sheet/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download unreadable.txt", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Download archive.bin", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Download large.bin", exact: true })).toHaveCount(0);
  await expect(page.locator("#outputs-body")).toContainText("This file is too large to embed (6.0 MiB)");
  await expect(page.locator("#outputs-body")).toContainText(String.raw`C:\workspace\large.bin`);
  await expect(page.locator("iframe")).toHaveCount(0);
  await checkAccessibility(page);
  const preview = page.locator("#outputs-body summary");
  await preview.press("Enter");
  await expect(page.locator("iframe")).toHaveAttribute("title", "PDF output: document.pdf");
  await preview.press("Enter");
  await expect(page.locator("iframe")).not.toBeVisible();
  await page.getByRole("button", { name: "Previous Output" }).press("Enter");
  await expect(page.getByRole("link", { name: "Download previous data.xlsx" })).toBeVisible();
  await checkAccessibility(page);
});

test("missing spreadsheet parser reports an error without removing downloads", async ({ page }) => {
  await openFile(page, "media.html");
  await expect(page.getByRole("link", { name: "Download data.xlsx", exact: true })).toBeVisible();
  await expect(page.locator("#outputs-body")).toContainText("Error rendering spreadsheet");
  await checkAccessibility(page);
});
