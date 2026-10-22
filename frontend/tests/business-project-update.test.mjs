import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(new URL("../src/IndustryModules.vue", import.meta.url), "utf8");
const saveSource = source.slice(source.indexOf("async function saveProject()"), source.indexOf("function editProject("));
const saveProject = new Function("editingProjectId", "projectForm", "run", "request", "resetProject", `${saveSource}; return saveProject;`);

for (const editing of [null, 17]) {
  test(`project ${editing ? "update preserves" : "creation includes"} customer`, async () => {
    let sent;
    const form = { customer_id: "9", title: "Project", budget: "100", assigned_user_id: "", starts_on: "", due_on: "", description: "" };
    await saveProject({ value: editing }, form, async (action) => { await action(); return true; }, async (url, options) => { sent = { url, ...options, payload: JSON.parse(options.body) }; }, () => {})();
    assert.equal(sent.method, editing ? "PATCH" : "POST");
    assert.equal(sent.url, editing ? "/commercial/projects/17" : "/commercial/projects");
    assert.equal(Object.hasOwn(sent.payload, "customer_id"), !editing);
    if (!editing) assert.equal(sent.payload.customer_id, 9);
    assert.equal(form.customer_id, "9");
    assert.equal(sent.payload.budget, 100);
    assert.equal(sent.payload.starts_on, null);
  });
}

test("project customer selector is disabled while editing", () => {
  const selector = source.match(/<select\s+v-model="projectForm\.customer_id"[^>]*>/)?.[0];
  assert.match(selector || "", /:disabled="Boolean\(editingProjectId\)"/);
});
