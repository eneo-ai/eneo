import { expect, test } from "@playwright/test";
import { BACKEND_URL, backendFetch, expectOk, uniqueName } from "./helpers";

test("an API key can read assistants until it is revoked", async ({ page, request }) => {
  test.setTimeout(60_000);

  await page.goto("/");

  const keyName = uniqueName("E2E API key");
  const createResponse = await backendFetch(page, request, "/api/v1/api-keys", {
    method: "POST",
    data: {
      name: keyName,
      description: "Created by Playwright e2e",
      key_type: "sk_",
      permission: "read",
      scope_type: "tenant",
      ownership: "user",
      resource_permissions: {
        assistants: "read"
      }
    }
  });
  await expectOk(createResponse, "creating API key");
  expect(createResponse.status()).toBe(201);

  const created = await createResponse.json();
  const secret = created.secret as string;
  const keyId = created.api_key.id as string;

  const externalRead = await request.get(`${BACKEND_URL}/api/v1/assistants/`, {
    headers: { "X-API-Key": secret }
  });
  await expectOk(externalRead, "reading assistants with API key");

  const revokeResponse = await backendFetch(page, request, `/api/v1/api-keys/${keyId}/revoke`, {
    method: "POST",
    data: {
      reason_code: "user_request",
      reason_text: "E2E lifecycle cleanup"
    }
  });
  await expectOk(revokeResponse, "revoking API key");
  expect((await revokeResponse.json()).state).toBe("revoked");

  const revokedRead = await request.get(`${BACKEND_URL}/api/v1/assistants/`, {
    headers: { "X-API-Key": secret }
  });
  expect(revokedRead.status()).toBeGreaterThanOrEqual(400);

  const revokedKeyResponse = await backendFetch(page, request, `/api/v1/api-keys/${keyId}`);
  await expectOk(revokedKeyResponse, "loading revoked API key");
  const revokedKey = await revokedKeyResponse.json();
  expect(revokedKey.name).toBe(keyName);
  expect(revokedKey.state).toBe("revoked");
});
