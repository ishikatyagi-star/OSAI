import { expect, test, type Page, type Route } from "@playwright/test";
import { mockEmptyNotificationInbox, mockExternalFonts } from "./helpers";

type Member = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  department_id: string | null;
  department: string | null;
  data_tier: string;
  status: string;
};

type Department = {
  id: string;
  name: string;
  color: string;
  members: number;
};

type Invite = {
  id: string;
  email: string;
  role: string;
  department_id: string | null;
  data_tier: string;
  status: string;
  invite_link: string;
};

const session = {
  user_id: "qa-admin",
  email: "admin@example.test",
  display_name: "QA Admin",
  org_id: "qa-org",
  org_name: "QA Workspace",
  role: "admin",
  is_admin: true,
  data_tier: "red",
  permissions: [],
  department_id: null,
};

const metrics = {
  total_documents: 0,
  documents_by_connector: {},
  documents_by_tier: {},
  connectors_connected: 0,
  connector_statuses: [],
  pending_decisions: 0,
  pending_actions: 0,
  recent_decisions: [],
  sync_runs_total: 0,
  sync_runs_succeeded: 0,
  last_sync_at: null,
  members: 3,
  departments: 1,
  automations: 0,
  as_of: "2026-07-22T10:00:00Z",
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function seedSignedInAdmin(page: Page) {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
    localStorage.setItem("osai_user_id", "qa-admin");
    localStorage.setItem("osai_user_email", "admin@example.test");
    localStorage.setItem("osai_user_name", "QA Admin");
  });
  await page.route("**/api/auth/session", (route) => json(route, session));
  await page.route("**/api/dashboard/metrics", (route) => json(route, metrics));
}

test("admin completes the API-backed Team lifecycle without duplicate writes", async ({
  page,
}) => {
  await seedSignedInAdmin(page);

  let members: Member[] = [
    {
      id: "qa-admin",
      email: "admin@example.test",
      display_name: "QA Admin",
      role: "admin",
      department_id: null,
      department: null,
      data_tier: "red",
      status: "active",
    },
    {
      id: "member-alice",
      email: "alice@example.test",
      display_name: "Alice Analyst",
      role: "member",
      department_id: "dept-engineering",
      department: "Engineering",
      data_tier: "amber",
      status: "active",
    },
    {
      id: "member-bob",
      email: "bob@example.test",
      display_name: "Bob Builder",
      role: "member",
      department_id: null,
      department: null,
      data_tier: "normal",
      status: "active",
    },
  ];
  let departments: Department[] = [
    {
      id: "dept-engineering",
      name: "Engineering",
      color: "#2563eb",
      members: 1,
    },
  ];
  let invites: Invite[] = [];
  const mutations: string[] = [];
  const firstDepartmentCreate = deferred();
  let departmentCreateAttempts = 0;

  const listedMembers = () =>
    members.map((member) => {
      const department = departments.find((item) => item.id === member.department_id);
      return { ...member, department: department?.name ?? null };
    });
  const syncDepartmentCounts = () => {
    departments = departments.map((department) => ({
      ...department,
      members: members.filter((member) => member.department_id === department.id).length,
    }));
  };
  const listedDepartments = () =>
    departments.map((department) => ({
      ...department,
      members: members.filter((member) => member.department_id === department.id).length,
    }));

  await page.route("**/api/team/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path === "/api/team/members" && method === "GET") {
      return json(route, listedMembers());
    }
    if (path === "/api/team/departments" && method === "GET") {
      return json(route, listedDepartments());
    }
    if (path === "/api/team/invites" && method === "GET") {
      return json(route, invites);
    }

    const body = request.postData() ? await request.postDataJSON() : null;
    mutations.push(`${method} ${path}${url.search} ${JSON.stringify(body)}`);

    if (path === "/api/team/departments" && method === "POST") {
      expect(body).toEqual({ name: "Quality Assurance" });
      departmentCreateAttempts += 1;
      if (departmentCreateAttempts === 1) {
        await firstDepartmentCreate.promise;
        return json(route, { detail: "Department service unavailable" }, 503);
      }
      const department = {
        id: "dept-quality",
        name: "Quality Assurance",
        color: "#16a34a",
        members: 0,
      };
      departments = [...departments, department];
      return json(route, department);
    }

    if (path === "/api/team/departments/dept-quality" && method === "PATCH") {
      expect(body).toEqual({ name: "Quality Operations" });
      departments = departments.map((department) =>
        department.id === "dept-quality"
          ? { ...department, name: "Quality Operations" }
          : department
      );
      return json(route, {
        id: "dept-quality",
        name: "Quality Operations",
        color: "#16a34a",
      });
    }

    if (path === "/api/team/departments/dept-quality" && method === "DELETE") {
      expect(body).toBeNull();
      departments = departments.filter((department) => department.id !== "dept-quality");
      return json(route, { deleted: true });
    }

    if (path === "/api/team/invites" && method === "POST") {
      expect(body).toEqual({
        email: "invitee@example.test",
        role: "member",
        department_id: "dept-quality",
        data_tier: "amber",
      });
      const invite = {
        id: "invite-quality",
        email: "invitee@example.test",
        role: "member",
        department_id: "dept-quality",
        data_tier: "amber",
        status: "pending",
        invite_link: "https://app.example.test/login#invite=qa-token",
      };
      invites = [invite];
      return json(route, invite);
    }

    if (path === "/api/team/invites/invite-quality" && method === "DELETE") {
      expect(body).toBeNull();
      invites = [];
      return json(route, { revoked: true });
    }

    if (path === "/api/team/members/member-bob" && method === "PATCH") {
      expect([
        { role: "admin" },
        { department_id: "dept-quality" },
        { department_id: null },
        { role: "member" },
      ]).toContainEqual(body);
      members = members.map((member) =>
        member.id === "member-bob" ? { ...member, ...(body as Partial<Member>) } : member
      );
      syncDepartmentCounts();
      const member = members.find((item) => item.id === "member-bob")!;
      return json(route, {
        id: member.id,
        role: member.role,
        department_id: member.department_id,
        data_tier: member.data_tier,
      });
    }

    if (
      path === "/api/team/members/member-alice/removal-impact" &&
      method === "GET"
    ) {
      expect(body).toBeNull();
      return json(route, {
        member_id: "member-alice",
        member_email: "alice@example.test",
        member_display_name: "Alice Analyst",
        assets: {
          automations: 1,
          private_threads: 1,
          shared_threads: 0,
          workflow_runs: 0,
        },
        blockers: {
          owned_uploads: 0,
          document_access_grants: 0,
          private_memories: 0,
          ask_exchanges: 0,
          pending_connector_actions: 0,
        },
        preserved: { saved_artifacts: 2 },
        total_assets: 2,
        total_blockers: 0,
        requires_transfer: true,
        blocked: false,
      });
    }

    if (
      path === "/api/team/members/member-alice" &&
      url.search === "?transfer_to_user_id=member-bob" &&
      method === "DELETE"
    ) {
      expect(body).toBeNull();
      members = members.filter((member) => member.id !== "member-alice");
      syncDepartmentCounts();
      return json(route, { deleted: true });
    }

    throw new Error(`Unexpected Team API request: ${method} ${path}${url.search}`);
  });

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/team");

  await expect(page.getByRole("heading", { name: "Team" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Members (3)" })).toBeVisible();

  await page.getByRole("tab", { name: "Departments (1)" }).click();
  const departmentName = page.getByLabel("New department name");
  const addDepartment = page.getByRole("button", { name: "Add", exact: true });
  await departmentName.fill("Quality Assurance");
  await addDepartment.click();

  await expect.poll(() => departmentCreateAttempts).toBe(1);
  await expect(departmentName).toBeDisabled();
  await expect(page.getByRole("button", { name: "Adding...", exact: true })).toBeDisabled();
  await page.keyboard.press("Enter");
  await page.evaluate(() => new Promise(requestAnimationFrame));
  expect(departmentCreateAttempts).toBe(1);

  firstDepartmentCreate.resolve();
  await expect(page.locator(".card[role='alert']")).toContainText(
    "Department service unavailable"
  );
  await expect(departmentName).toHaveValue("Quality Assurance");
  await expect(addDepartment).toBeEnabled();

  await addDepartment.click();
  await expect(page.getByText("Quality Assurance", { exact: true })).toHaveCount(1);
  expect(departmentCreateAttempts).toBe(2);

  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("prompt");
    expect(dialog.message()).toBe("Rename department");
    expect(dialog.defaultValue()).toBe("Quality Assurance");
    await dialog.accept("Quality Operations");
  });
  await page.getByRole("button", { name: "Rename Quality Assurance" }).click();
  await expect(page.getByText("Quality Operations", { exact: true })).toBeVisible();
  await expect(page.getByText("Quality Assurance", { exact: true })).toHaveCount(0);

  await page.getByRole("tab", { name: "Members (3)" }).click();
  const bobRole = page.getByRole("combobox", { name: "Role for Bob Builder" });
  await bobRole.click();
  await page.getByRole("option", { name: "admin", exact: true }).click();
  await expect(bobRole).toHaveText("admin");
  await expect(
    page.getByRole("combobox", { name: "Data access for Bob Builder" })
  ).toHaveCount(0);

  const bobDepartment = page.getByRole("combobox", {
    name: "Department for Bob Builder",
  });
  await bobDepartment.click();
  await page.getByRole("option", { name: "Quality Operations", exact: true }).click();
  await expect(bobDepartment).toHaveText("Quality Operations");

  await page.getByRole("tab", { name: "Invites (0)" }).click();
  await page.getByLabel("Work email").fill("invitee@example.test");
  await page.getByRole("combobox", { name: "Invite data access" }).click();
  await page.getByRole("option", { name: "Amber", exact: true }).click();
  await page.getByRole("combobox", { name: "Invite department" }).click();
  await page.getByRole("option", { name: "Quality Operations", exact: true }).click();
  await page.getByRole("button", { name: "Create invite link" }).click();

  const inviteRow = page.getByRole("row").filter({ hasText: "invitee@example.test" });
  await expect(inviteRow).toHaveCount(1);
  await expect(inviteRow).toContainText("member");
  await expect(inviteRow).toContainText("Amber");

  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("confirm");
    expect(dialog.message()).toBe(
      "Revoke the invite link for invitee@example.test?"
    );
    await dialog.accept();
  });
  await inviteRow.getByRole("button", { name: "Revoke" }).click();
  await expect(inviteRow).toHaveCount(0);
  await expect(page.getByText("No pending invites.", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "Members (3)" }).click();
  const aliceRow = page.getByRole("row").filter({ hasText: "alice@example.test" });
  await aliceRow.getByRole("button", { name: "Remove" }).click();

  const removalDialog = page.getByRole("dialog", {
    name: "Remove alice@example.test",
  });
  await expect(removalDialog.getByText("Removal impact", { exact: true })).toBeVisible();
  await expect(removalDialog.getByText("1 automation", { exact: true })).toBeVisible();
  await expect(
    removalDialog.getByText("1 private conversation", { exact: true })
  ).toBeVisible();
  await expect(removalDialog).toContainText(
    "2 saved artifacts keep the original creator label"
  );
  const transfer = removalDialog.getByRole("combobox", {
    name: "Transfer assets owned by alice@example.test to",
  });
  await transfer.click();
  await page
    .getByRole("option", { name: "Bob Builder (bob@example.test)", exact: true })
    .click();
  await expect(removalDialog.getByRole("status")).toContainText(
    "Bob Builder will receive ownership"
  );
  await removalDialog.getByRole("button", { name: "Transfer and remove" }).click();

  await expect(removalDialog).toBeHidden();
  await expect(page.getByText("alice@example.test", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Members (2)" })).toBeVisible();

  await bobDepartment.click();
  await page.getByRole("option", { name: "- Unassigned -", exact: true }).click();
  await expect(bobDepartment).toHaveText("- Unassigned -");
  await bobRole.click();
  await page.getByRole("option", { name: "member", exact: true }).click();
  await expect(bobRole).toHaveText("member");

  await page.getByRole("tab", { name: "Departments (2)" }).click();
  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("confirm");
    expect(dialog.message()).toBe("Delete the Quality Operations department?");
    await dialog.accept();
  });
  await page.getByRole("button", { name: "Delete Quality Operations" }).click();

  await expect(page.getByText("Quality Operations", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Departments (1)" })).toBeVisible();
  await expect(page.getByText("Engineering", { exact: true })).toBeVisible();
  await expect(page.getByText("0 members", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Invites (0)" }).click();
  await expect(page.getByText("No pending invites.", { exact: true })).toBeVisible();

  expect(members).toMatchObject([
    { id: "qa-admin", role: "admin", department_id: null },
    { id: "member-bob", role: "member", department_id: null },
  ]);
  expect(departments).toEqual([
    {
      id: "dept-engineering",
      name: "Engineering",
      color: "#2563eb",
      members: 0,
    },
  ]);
  expect(invites).toEqual([]);
  expect(mutations).toEqual([
    'POST /api/team/departments {"name":"Quality Assurance"}',
    'POST /api/team/departments {"name":"Quality Assurance"}',
    'PATCH /api/team/departments/dept-quality {"name":"Quality Operations"}',
    'PATCH /api/team/members/member-bob {"role":"admin"}',
    'PATCH /api/team/members/member-bob {"department_id":"dept-quality"}',
    'POST /api/team/invites {"email":"invitee@example.test","role":"member","department_id":"dept-quality","data_tier":"amber"}',
    "DELETE /api/team/invites/invite-quality null",
    "GET /api/team/members/member-alice/removal-impact null",
    "DELETE /api/team/members/member-alice?transfer_to_user_id=member-bob null",
    'PATCH /api/team/members/member-bob {"department_id":null}',
    'PATCH /api/team/members/member-bob {"role":"member"}',
    "DELETE /api/team/departments/dept-quality null",
  ]);
  expect(pageErrors).toEqual([]);
});
