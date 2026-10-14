import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const previewSource = fs.readFileSync(new URL("../src/DataRagPreview.vue", import.meta.url), "utf8");
const apiSource = fs.readFileSync(new URL("../../backend/app/api/recommendations.py", import.meta.url), "utf8");

test("Data_RAG model preview is available in the experiment workspace and stays synthetic/read-only", () => {
  assert.match(appSource, /<DataRagPreview :api-base="API_BASE"\s*\/>/);
  assert.match(previewSource, /recommendations\/demo\/preview/);
  assert.match(previewSource, /Chỉ xem thử · không gửi tin cho khách/);
  assert.match(previewSource, /Số nhóm là mã nhận diện, không phải mức VIP/);
  assert.match(apiSource, /@router\.post\("\/demo\/preview", dependencies=\[Depends\(require_admin_access\)\]\)/);
  assert.match(apiSource, /data_scope": "synthetic"/);
  const previewStart = apiSource.indexOf("def preview_data_rag");
  const nextRoute = apiSource.indexOf("@router.post(", previewStart + 1);
  assert.doesNotMatch(apiSource.slice(previewStart, nextRoute), /get_tenant_db|db\.add|commit\(/);
});
