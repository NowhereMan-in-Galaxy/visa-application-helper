const CATEGORY_LABELS = {
  passport_scan: "证件", // 护照 / 身份证 / 户口本都归在这一类——用户的原话是"这几个算一类证件"
  financial_snapshot: "财务状态",
  employment_doc: "职业材料",
  id_photo: "证件照",
};

// "个人材料" tab：跟"我是谁"相关、不属于任何具体一次申请的长期资产，belongs_to 为空
// （见 src/core/models.py 的 MaterialRecord.belongs_to 注释），走 GET/POST /api/materials，
// 不看是哪次签证申请。
const PERSONAL_CATEGORIES = ["passport_scan", "id_photo"];

// "办事材料准备" tab：这次申请要交的证明材料，仍然挂在某个具体 VisaApplication 下
// （belongs_to = 申请 id），走 GET/POST /api/visa-applications/{id}/materials。
const TASK_CATEGORIES = ["financial_snapshot", "employment_doc"];

const selectEl = document.getElementById("application-select");
const personalGroupsEl = document.getElementById("material-groups-personal");
const taskGroupsEl = document.getElementById("material-groups-task");
const emptyStateEl = document.getElementById("empty-state");
const addMaterialTemplate = document.getElementById("add-material-template");

const travelHistoryListEl = document.getElementById("travel-history-list");
const travelHistoryEmptyEl = document.getElementById("travel-history-empty");
const travelHistoryToggleEl = document.getElementById("travel-history-toggle");
const travelHistoryFormEl = document.getElementById("travel-history-form");
const editTravelHistoryTemplate = document.getElementById("edit-travel-history-template");

let currentApplicationId = null;

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`请求 ${url} 失败：HTTP ${response.status} ${body}`);
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

// ---------- 材料列表 ----------

function buildAddMaterialForm(category, submitUrl, onSaved) {
  const fragment = addMaterialTemplate.content.cloneNode(true);
  const wrapper = document.createElement("div");
  wrapper.className = "add-material-block";
  wrapper.appendChild(fragment);

  const toggleButton = wrapper.querySelector("[data-add-material]");
  const form = wrapper.querySelector("[data-material-form]");
  const cancelButton = form.querySelector("[data-cancel]");

  toggleButton.addEventListener("click", () => {
    form.hidden = !form.hidden;
  });
  cancelButton.addEventListener("click", () => {
    form.reset();
    form.hidden = true;
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    formData.set("category", category);
    if (!formData.get("file")?.name) {
      formData.delete("file"); // 没选文件的话别把空文件字段一起发过去
    }

    try {
      await fetchJSON(submitUrl, { method: "POST", body: formData });
      form.reset();
      form.hidden = true;
      await onSaved();
    } catch (error) {
      alert(`保存失败：${error.message}`);
    }
  });

  return wrapper;
}

function groupByCategory(materials, categories) {
  const byCategory = new Map();
  for (const category of categories) {
    byCategory.set(category, []);
  }
  for (const material of materials) {
    byCategory.get(material.category)?.push(material);
  }
  return byCategory;
}

function renderPersonalMaterials(materials) {
  personalGroupsEl.innerHTML = "";
  const byCategory = groupByCategory(materials, PERSONAL_CATEGORIES);

  for (const category of PERSONAL_CATEGORIES) {
    const section = document.createElement("section");
    section.className = "category-group";

    const heading = document.createElement("h2");
    heading.textContent = CATEGORY_LABELS[category] ?? category;
    section.appendChild(heading);

    for (const material of byCategory.get(category)) {
      section.appendChild(renderMaterialRow(material, loadPersonalMaterials));
    }

    section.appendChild(
      buildAddMaterialForm(category, "/api/materials", loadPersonalMaterials)
    );

    personalGroupsEl.appendChild(section);
  }
}

function renderTaskMaterials(materials) {
  taskGroupsEl.innerHTML = "";
  const byCategory = groupByCategory(materials, TASK_CATEGORIES);

  for (const category of TASK_CATEGORIES) {
    const section = document.createElement("section");
    section.className = "category-group";

    const heading = document.createElement("h2");
    heading.textContent = CATEGORY_LABELS[category] ?? category;
    section.appendChild(heading);

    const refreshTask = () => loadMaterialsFor(currentApplicationId);
    for (const material of byCategory.get(category)) {
      section.appendChild(renderMaterialRow(material, refreshTask));
    }

    section.appendChild(
      buildAddMaterialForm(
        category,
        `/api/visa-applications/${currentApplicationId}/materials`,
        refreshTask
      )
    );

    taskGroupsEl.appendChild(section);
  }
}

function buildAppendPageForm(material, onAppended) {
  const form = document.createElement("form");
  form.className = "inline-form append-page-form";

  const label = document.createElement("label");
  label.textContent = "新的一页（图片或 PDF）";
  const input = document.createElement("input");
  input.type = "file";
  input.name = "file";
  input.accept = ".pdf,.jpg,.jpeg,.png";
  input.required = true;
  label.appendChild(input);
  form.appendChild(label);

  const actions = document.createElement("div");
  actions.className = "form-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.textContent = "追加";
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.textContent = "取消";
  cancelButton.addEventListener("click", () => form.remove());
  actions.appendChild(saveButton);
  actions.appendChild(cancelButton);
  form.appendChild(actions);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    try {
      await fetchJSON(`/api/materials/${material.id}/append-page`, {
        method: "POST",
        body: formData,
      });
      await onAppended();
    } catch (error) {
      alert(`追加失败：${error.message}`);
    }
  });

  return form;
}

function renderMaterialRow(material, onChanged) {
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

  const fileRef = document.createElement("span");
  fileRef.className = "file-ref";
  fileRef.textContent = material.file_ref ? material.file_ref : "（还没有对应文件）";
  row.appendChild(fileRef);

  // 只有已经有 PDF 文件的记录才能"追加新页"——单页图片、还没上传文件的记录都不显示这个入口，
  // 后端 append-page 接口对这两种情况本来就会拒绝（见 src/api/app.py）。
  if (material.file_ref && material.file_ref.toLowerCase().endsWith(".pdf")) {
    const appendButton = document.createElement("button");
    appendButton.type = "button";
    appendButton.className = "edit-link";
    appendButton.textContent = "+ 追加新页";
    appendButton.addEventListener("click", () => {
      const existingForm = row.querySelector("form");
      if (existingForm) {
        existingForm.remove();
        return;
      }
      row.appendChild(buildAppendPageForm(material, onChanged));
    });
    row.appendChild(appendButton);
  }

  return row;
}

async function loadMaterialsFor(applicationId) {
  currentApplicationId = applicationId;
  const materials = await fetchJSON(`/api/visa-applications/${applicationId}/materials`);
  renderTaskMaterials(materials);
}

async function loadPersonalMaterials() {
  const materials = await fetchJSON("/api/materials");
  renderPersonalMaterials(materials);
}

// ---------- 个人信息 & 出行记录 ----------

function describeTravelHistoryEntry(entry) {
  const country = entry.country ?? "（国家待补充）";
  const range = entry.exit_date ? `${entry.entry_date} ~ ${entry.exit_date}` : `${entry.entry_date} ~ 至今`;
  const purpose = entry.purpose ? `（${entry.purpose}）` : "";
  return `${country}：${range}${purpose}`;
}

function buildEditTravelHistoryForm(entry, originalIndex) {
  const fragment = editTravelHistoryTemplate.content.cloneNode(true);
  const form = fragment.querySelector("[data-edit-form]");

  form.elements.country.value = entry.country ?? "";
  form.elements.entry_date.value = entry.entry_date;
  form.elements.exit_date.value = entry.exit_date ?? "";
  form.elements.purpose.value = entry.purpose ?? "";

  form.querySelector("[data-cancel]").addEventListener("click", () => {
    form.remove();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = {
      country: formData.get("country") || null,
      entry_date: formData.get("entry_date"),
      exit_date: formData.get("exit_date") || null,
      purpose: formData.get("purpose") || null,
    };

    try {
      await fetchJSON(`/api/personal-profile/travel-history/${originalIndex}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await loadPersonalProfile();
    } catch (error) {
      alert(`保存失败：${error.message}`);
    }
  });

  return form;
}

function renderTravelHistory(profile) {
  travelHistoryListEl.innerHTML = "";
  // 存储顺序是"什么时候补录的"，不一定是时间顺序（尤其是批量导入 + 手动补充混在一起时），
  // 展示的时候按入境日期重新排一遍，读起来才是一条自然的时间线；但"编辑哪一条"用的是
  // 它在 materials_root/personal-profile.yaml 里的原始位置（originalIndex），不是排序后的位置。
  const entriesWithIndex = (profile.travel_history ?? []).map((entry, originalIndex) => ({
    entry,
    originalIndex,
  }));
  entriesWithIndex.sort((a, b) => a.entry.entry_date.localeCompare(b.entry.entry_date));

  travelHistoryEmptyEl.hidden = entriesWithIndex.length !== 0;

  for (const { entry, originalIndex } of entriesWithIndex) {
    const li = document.createElement("li");
    if (!entry.country) {
      li.classList.add("needs-country");
    }

    const textSpan = document.createElement("span");
    textSpan.textContent = describeTravelHistoryEntry(entry);
    li.appendChild(textSpan);

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "edit-link";
    editButton.textContent = "编辑";
    editButton.addEventListener("click", () => {
      const existingForm = li.querySelector("form");
      if (existingForm) {
        existingForm.remove();
        return;
      }
      li.appendChild(buildEditTravelHistoryForm(entry, originalIndex));
    });
    li.appendChild(editButton);

    travelHistoryListEl.appendChild(li);
  }
}

async function loadPersonalProfile() {
  const profile = await fetchJSON("/api/personal-profile");
  renderTravelHistory(profile);
}

travelHistoryToggleEl.addEventListener("click", () => {
  travelHistoryFormEl.hidden = !travelHistoryFormEl.hidden;
});
travelHistoryFormEl.querySelector("[data-cancel]").addEventListener("click", () => {
  travelHistoryFormEl.reset();
  travelHistoryFormEl.hidden = true;
});
travelHistoryFormEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(travelHistoryFormEl);
  const payload = {
    country: formData.get("country"),
    entry_date: formData.get("entry_date"),
    exit_date: formData.get("exit_date") || null,
    purpose: formData.get("purpose") || null,
  };

  try {
    await fetchJSON("/api/personal-profile/travel-history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    travelHistoryFormEl.reset();
    travelHistoryFormEl.hidden = true;
    await loadPersonalProfile();
  } catch (error) {
    alert(`保存失败：${error.message}`);
  }
});

// ---------- Tab 切换 ----------

function setupTabs() {
  const buttons = document.querySelectorAll(".tab-button");
  const panels = document.querySelectorAll("[data-tab-panel]");

  for (const button of buttons) {
    button.addEventListener("click", () => {
      const targetTab = button.dataset.tab;
      for (const b of buttons) {
        b.classList.toggle("active", b === button);
      }
      for (const panel of panels) {
        panel.hidden = panel.dataset.tabPanel !== targetTab;
      }
    });
  }

  buttons[0]?.classList.add("active");
}

// ---------- 初始化 ----------

async function init() {
  setupTabs();

  // "个人材料" tab 不依赖任何签证申请，哪怕下面申请列表是空的，这块也应该正常显示。
  await loadPersonalProfile();
  await loadPersonalMaterials();

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
