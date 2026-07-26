import { expect, test } from "@playwright/test";

const mockBackendUrl = `http://127.0.0.1:${process.env.WARDN_E2E_BACKEND_PORT ?? 4100}`;
const sessionCookieName = process.env.WARDN_E2E_SESSION_COOKIE_NAME ?? "wardn_e2e_session";

test("completes OIDC through the same-origin login and callback bridge", async ({
  baseURL,
  page,
  request,
}) => {
  await request.post(`${mockBackendUrl}/__test/reset`, {
    data: { authMode: "oidc" },
  });

  await page.goto("/login?error=oidc&next=%2Forg");
  await expect(page.getByRole("button", { name: "Sign in with Zitadel" })).toBeVisible();
  await page.getByRole("button", { name: "Sign in with Zitadel" }).click();
  await expect(page).toHaveURL(/\/favicon\.ico\?oidc-provider=1/);

  const loginCookies = await page.context().cookies(baseURL);
  expect(loginCookies).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        name: "wardn_oidc_state_test",
        value: "state-cookie",
      }),
    ])
  );

  await page.goto("/api/auth/oidc/callback?code=test-code&state=test-state");
  await expect(page).toHaveURL(/\/org$/);

  const callbackCookies = await page.context().cookies(baseURL);
  expect(callbackCookies).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        name: sessionCookieName,
        value: "test-session",
      }),
    ])
  );
  expect(callbackCookies.some((cookie) => cookie.name === "wardn_oidc_state_test")).toBeFalsy();
});

test("moves OIDC login to the configured canonical origin before setting state", async ({
  baseURL,
  request,
}) => {
  const response = await request.get("/api/auth/oidc/login?redirectTo=%2Forg", {
    headers: {
      "x-forwarded-host": "alternate.example.com",
      "x-forwarded-proto": "http",
    },
    maxRedirects: 0,
  });

  expect(response.status()).toBe(307);
  expect(response.headers().location).toBe(`${baseURL}/api/auth/oidc/login?redirectTo=%2Forg`);
  expect(response.headers()["set-cookie"]).toBeUndefined();
});
