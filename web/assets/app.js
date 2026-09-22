const CATEGORY_LABELS = {
  personal_info: "个人信息",
  passport_scan: "护照扫描件",
  financial_snapshot: "财务状态",
  employment_doc: "职业材料",
  id_photo: "证件照",
};

// 渲染顺序固定，跟 spec.md FR-001 里列出的顺序一致，每次打开页面材料分组的顺序不会跳来跳去。
const CATEGORY_ORDER = [
  "personal_info",
  "passport_scan",
  "financial_snapshot",
  "employment_doc",
  "id_photo",
];

const selectEl = document.getElementById("application-select");
const groupsEl = document.getElementById("material-groups");
const emptyStateEl = document.getElementById("empty-state");

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`请求 ${url} 失败：HTTP ${response.status}`);
  }
  return response.json();
}

function formatUpdateReminder(material) {
  if (material.update_days_until_due === null || material.update_days_until_due === undefined) {
    return "";
  }
  const days = material.update_days_until_due;
  if (material.update_overdue) {
    return `建议更新已过期 ${Math.abs(days)} 天`;
  }
  return `距建议更新还有 ${days} 天`;
}

function renderMaterials(materials) {
  groupsEl.innerHTML = "";

  if (materials.length === 0) {
    emptyStateEl.hidden = false;
    return;
  }
  emptyStateEl.hidden = true;

  const byCategory = new Map();
  for (const category of CATEGORY_ORDER) {
    byCategory.set(category, []);
  }
  for (const material of materials) {
    byCategory.get(material.category).push(material);
  }

  for (const category of CATEGORY_ORDER) {
    const items = byCategory.get(category);
    if (items.length === 0) continue;

    const section = document.createElement("section");
    section.className = "category-group";

    const heading = document.createElement("h2");
    heading.textContent = CATEGORY_LABELS[category] ?? category;
    section.appendChild(heading);

    for (const material of items) {
      const row = document.createElement("div");
      row.className = "material-row";

      const name = document.createElement("span");
      name.className = "material-name";
      name.textContent = material.type;
      row.appendChild(name);

      if (material.sublabel) {
        const sublabel = document.createElement("span");
        sublabel.className = "material-sublabel";
        sublabel.textContent = material.sublabel;
        row.appendChild(sublabel);
      }

      const badge = document.createElement("span");
      badge.className = `status-badge status-${material.status}`;
      badge.textContent = material.status;
      row.appendChild(badge);

      const reminderText = formatUpdateReminder(material);
      if (reminderText) {
        const reminder = document.createElement("span");
        reminder.className = "update-reminder" + (material.update_overdue ? " overdue" : "");
        reminder.textContent = reminderText;
        row.appendChild(reminder);
      }

      section.appendChild(row);
    }

    groupsEl.appendChild(section);
  }
}

async function loadMaterialsFor(applicationId) {
  const materials = await fetchJSON(`/api/visa-applications/${applicationId}/materials`);
  renderMaterials(materials);
}

async function init() {
  const applications = await fetchJSON("/api/visa-applications");

  if (applications.length === 0) {
    emptyStateEl.textContent = "还没有任何签证申请——在 materials_index/applications/ 里加一个 YAML 文件就会出现在这里。";
    emptyStateEl.hidden = false;
    return;
  }

  for (const application of applications) {
    const option = document.createElement("option");
    option.value = application.id;
    option.textContent = `${application.country} · ${application.visa_type}（截止 ${application.deadline}）`;
    selectEl.appendChild(option);
  }

  selectEl.addEventListener("change", () => loadMaterialsFor(selectEl.value));
  await loadMaterialsFor(applications[0].id);
}

init().catch((error) => {
  emptyStateEl.textContent = `加载失败：${error.message}`;
  emptyStateEl.hidden = false;
});
