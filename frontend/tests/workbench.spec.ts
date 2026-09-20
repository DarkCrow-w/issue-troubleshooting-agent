import { test, expect } from "@playwright/test";

test("replay: investigate, navigate graph, inspect redacted evidence, export report", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "开始排查" })).toBeEnabled();
  await expect(
    page.getByRole("heading", { name: "这笔交易，哪里出了问题？" }),
  ).toBeVisible();
  await expect(page.getByLabel("开始时间")).not.toBeVisible();
  await page.screenshot({
    path: "../data/workbench-start.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "开始排查" }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  await expect(
    page.getByText("观测事实", { exact: false }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: "../data/workbench-report.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "调用链路", exact: true }).click();
  await expect(page.locator(".call-node")).toHaveCount(3);
  await expect(page.locator(".edge")).toHaveCount(2);
  await page.locator(".call-node").first().click();
  const drawer = page.getByRole("dialog", { name: "日志证据" });
  await expect(drawer).toContainText("[REDACTED]");
  await expect(drawer).not.toContainText("demo-secret-never-real");
  await page.getByRole("button", { name: "关闭证据" }).click();
  await page.getByRole("button", { name: "日志时间线", exact: true }).click();
  await expect(page.locator(".timeline button")).toHaveCount(7);
  await page.getByRole("button", { name: "执行详情", exact: true }).click();
  await expect(page.getByText("输入与消耗")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Markdown", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("investigation.md");
  expect(errors).toEqual([]);
});

test("mobile: form fits viewport and cleaning toggle works", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "开始排查" })).toBeEnabled();
  await page.locator(".settings summary").click();
  await page.getByRole("checkbox").uncheck();
  await page.locator(".settings summary").click();
  await page.getByRole("button", { name: "开始排查" }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../data/workbench-mobile.png",
    fullPage: true,
  });
});

test("cancel: request reaches API and UI reaches terminal state", async ({
  page,
}) => {
  await page.route("**/api/investigations", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({ json: { id: "cancel-test", status: "queued" } });
  });
  let cancelled = false;
  await page.route("**/api/investigations/cancel-test", (route) =>
    route.fulfill({
      json: {
        id: "cancel-test",
        status: cancelled ? "cancelled" : "running",
        phase: cancelled ? "任务已取消" : "查询日志",
        usage: {},
        report: null,
      },
    }),
  );
  await page.route("**/api/investigations/cancel-test/cancel", (route) => {
    cancelled = true;
    return route.fulfill({ json: { id: "cancel-test", status: "cancelled" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "开始排查" }).click();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByText("已取消", { exact: true })).toBeVisible();
  expect(cancelled).toBeTruthy();
});
