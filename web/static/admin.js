const initialTasks = window.adminInitialTasks || [];

const adminTaskList = document.getElementById("adminTaskList");
const adminListMeta = document.getElementById("adminListMeta");
const adminSearch = document.getElementById("adminSearch");
const adminUserFilter = document.getElementById("adminUserFilter");
const adminEditor = document.getElementById("adminEditor");
const adminEmpty = document.getElementById("adminEmpty");
const adminTaskTitle = document.getElementById("adminTaskTitle");
const adminTaskUser = document.getElementById("adminTaskUser");
const adminHeadingTags = document.getElementById("adminHeadingTags");
const adminTaskCreated = document.getElementById("adminTaskCreated");
const adminTaskStatus = document.getElementById("adminTaskStatus");
const adminFilename = document.getElementById("adminFilename");
const adminDownloadLink = document.getElementById("adminDownloadLink");
const adminPreviewWrap = document.getElementById("adminPreviewWrap");
const adminTaskText = document.getElementById("adminTaskText");
const adminAnswerText = document.getElementById("adminAnswerText");
const adminFlash = document.getElementById("adminFlash");
const prevTaskBtn = document.getElementById("prevTaskBtn");
const nextTaskBtn = document.getElementById("nextTaskBtn");
const refreshTasksBtn = document.getElementById("refreshTasksBtn");
const clearFiltersBtn = document.getElementById("clearFiltersBtn");
const saveAnswerBtnAdmin = document.getElementById("saveAnswerBtnAdmin");
const clearAnswerBtn = document.getElementById("clearAnswerBtn");
const deleteTaskBtn = document.getElementById("deleteTaskBtn");
const statTotal = document.getElementById("statTotal");
const statSolved = document.getElementById("statSolved");
const statOpen = document.getElementById("statOpen");
const filterButtons = [...document.querySelectorAll(".admin_filter_btn")];
const mobileListBtn = document.getElementById("mobileListBtn");
const mobileEditorBtn = document.getElementById("mobileEditorBtn");
const mobileRefreshBtn = document.getElementById("mobileRefreshBtn");

const state = {
  tasks: normalizeTasks(initialTasks),
  selectedTaskKey: null,
  filter: "all",
  query: "",
  userFilter: "",
  mobilePane: "list",
};

function normalizeTasks(tasks) {
  return [...tasks]
    .map((task) => ({
      ...task,
      task_number: String(task.task_number || ""),
      task_code: String(task.task_code || String(task.task_number || "").replace(".", "")),
      user_id: Number(task.user_id || 0),
      task_key: task.task_key || `${task.user_id || 0}:${task.task_number}`,
      answer_text: task.answer_text || "",
      task_text: task.task_text || "",
      filename: task.filename || "",
      created: task.created || "",
    }))
    .sort((a, b) =>
      a.task_number.localeCompare(b.task_number, undefined, { numeric: true }),
    );
}

function getFilteredTasks() {
  return state.tasks.filter((task) => {
    const answer = task.answer_text.trim();
    if (state.filter === "open" && answer) return false;
    if (state.filter === "solved" && !answer) return false;
    if (state.userFilter && String(task.user_id) !== state.userFilter) return false;

    if (!state.query) return true;
    const haystack = [
      `u${task.user_id}`,
      String(task.user_id),
      task.task_number,
      task.task_code,
      task.filename,
      task.created,
      task.answer_text,
      task.task_text,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(state.query);
  });
}

function renderStats() {
  statTotal.textContent = state.tasks.length;
  statSolved.textContent = state.tasks.filter((task) => task.answer_text.trim()).length;
  statOpen.textContent = state.tasks.filter((task) => !task.answer_text.trim()).length;
}

function renderUserFilter() {
  const users = [...new Set(state.tasks.map((task) => String(task.user_id)))].sort(
    (a, b) => Number(a) - Number(b),
  );
  const currentValue = state.userFilter;
  adminUserFilter.innerHTML = '<option value="">Все пользователи</option>';
  users.forEach((userId) => {
    const option = document.createElement("option");
    option.value = userId;
    option.textContent = `Пользователь ${userId}`;
    if (userId === currentValue) {
      option.selected = true;
    }
    adminUserFilter.appendChild(option);
  });
}

function renderTaskList() {
  const filtered = getFilteredTasks();
  adminTaskList.innerHTML = "";
  adminListMeta.textContent = filtered.length
    ? `Найдено ${filtered.length} заданий`
    : "Ничего не найдено";

  if (!filtered.length) {
    adminTaskList.innerHTML =
      '<div class="admin_list_empty">Ничего не найдено по текущему фильтру.</div>';
    renderEditor(null);
    return;
  }

  if (!filtered.some((task) => task.task_key === state.selectedTaskKey)) {
    state.selectedTaskKey = filtered[0].task_key;
  }

  filtered.forEach((task) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "admin_task_item";
    if (task.task_key === state.selectedTaskKey) {
      item.classList.add("active");
    }
    if (task.answer_text.trim()) {
      item.classList.add("is-solved");
    }
    item.dataset.task = task.task_number;
    item.innerHTML = `
      <span class="admin_task_num">№${task.task_number} User ${task.user_id}</span>
      <span class="admin_task_name">${escapeHtml(task.filename || "Без файла")}</span>
      <span class="admin_task_state">${task.answer_text.trim() ? "Есть ответ" : "Без ответа"}</span>
    `;
    item.addEventListener("click", () => {
      state.selectedTaskKey = task.task_key;
      state.mobilePane = "editor";
      renderTaskList();
      renderEditor(task);
    });
    adminTaskList.appendChild(item);
  });

  renderEditor(filtered.find((task) => task.task_key === state.selectedTaskKey) || null);
}

function renderEditor(task) {
  if (!task) {
    adminEditor.hidden = true;
    adminEmpty.hidden = false;
    adminHeadingTags.innerHTML = "";
    syncMobilePane();
    return;
  }

  adminEditor.hidden = false;
  adminEmpty.hidden = true;

  adminTaskTitle.textContent = `№${task.task_number}`;
  adminTaskUser.textContent = `User ${task.user_id}`;
  adminTaskCreated.textContent = task.created ? `Создано: ${task.created}` : "";
  adminTaskStatus.textContent = task.answer_text.trim() ? "Ответ сохранен" : "Без ответа";
  adminTaskStatus.classList.toggle("is-solved", Boolean(task.answer_text.trim()));
  adminFilename.textContent = task.filename || "Без файла";
  adminTaskText.textContent = (task.task_text || "").trim() || "У этого задания нет текста.";
  adminTaskText.classList.toggle("is-empty", !String(task.task_text || "").trim());
  adminAnswerText.value = task.answer_text || "";
  renderHeadingTags(task);

  renderPreview(task);
  syncNavigation();
  syncMobilePane();
}

function renderHeadingTags(task) {
  const tags = [];
  tags.push(`<span class="admin_tag">User ${task.user_id}</span>`);
  tags.push(`<span class="admin_tag">№${task.task_number}</span>`);
  tags.push(
    `<span class="admin_tag ${task.filename ? "is-active" : ""}">${task.filename ? "Есть файл" : "Без файла"}</span>`,
  );
  tags.push(
    `<span class="admin_tag ${(task.task_text || "").trim() ? "is-active" : ""}">${(task.task_text || "").trim() ? "Есть текст" : "Без текста"}</span>`,
  );
  tags.push(
    `<span class="admin_tag ${(task.answer_text || "").trim() ? "is-active" : ""}">${(task.answer_text || "").trim() ? "Есть ответ" : "Без ответа"}</span>`,
  );
  adminHeadingTags.innerHTML = tags.join("");
}

function renderPreview(task) {
  adminPreviewWrap.innerHTML = "";
  adminDownloadLink.hidden = true;

  if (!task.filename) {
    adminPreviewWrap.innerHTML =
      '<div class="admin_preview_empty">У этого задания нет файла. Можно работать только с текстом и ответом.</div>';
    return;
  }

  const fileUrl = `/files/${encodeURIComponent(task.filename)}`;
  adminDownloadLink.href = fileUrl;
  adminDownloadLink.hidden = false;

  const lowerName = task.filename.toLowerCase();
  const isImage = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"].some((ext) =>
    lowerName.endsWith(ext),
  );

  if (isImage) {
    const img = document.createElement("img");
    img.src = fileUrl;
    img.alt = `Задание ${task.task_number}`;
    img.className = "admin_preview_image";
    adminPreviewWrap.appendChild(img);
    return;
  }

  adminPreviewWrap.innerHTML =
    '<div class="admin_preview_empty">Предпросмотр для этого формата не поддерживается. Откройте файл отдельной ссылкой.</div>';
}

function syncNavigation() {
  const filtered = getFilteredTasks();
  const index = filtered.findIndex((task) => task.task_key === state.selectedTaskKey);
  prevTaskBtn.disabled = index <= 0;
  nextTaskBtn.disabled = index === -1 || index >= filtered.length - 1;
}

function updateTaskInState(updatedTask) {
  const normalized = normalizeTasks([updatedTask])[0];
  const keyIndex = state.tasks.findIndex((task) => task.task_key === normalized.task_key);
  if (keyIndex === -1) {
    state.tasks.push(normalized);
  } else {
    state.tasks[keyIndex] = normalized;
  }
  state.tasks.sort((a, b) =>
    a.task_number.localeCompare(b.task_number, undefined, { numeric: true }),
  );
}

async function saveCurrentTask(fields) {
  const task = state.tasks.find((item) => item.task_key === state.selectedTaskKey);
  if (!task) return;

  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(task.task_key)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      showFlash(data.error || "Не удалось сохранить", true);
      return;
    }

    updateTaskInState(data.task);
    renderStats();
    renderUserFilter();
    renderTaskList();
    state.mobilePane = "editor";
    syncMobilePane();
    showFlash("Сохранено");
  } catch (error) {
    showFlash("Не удалось сохранить", true);
  }
}

async function refreshTasks() {
  try {
    const response = await fetch("/api/tasks");
    const data = await response.json();
    if (!response.ok || !data.ok) {
      showFlash(data.error || "Не удалось обновить список", true);
      return;
    }
    state.tasks = normalizeTasks(data.tasks || []);
    if (!state.tasks.some((task) => task.task_key === state.selectedTaskKey)) {
      state.selectedTaskKey = state.tasks[0] ? state.tasks[0].task_key : null;
    }
    renderStats();
    renderUserFilter();
    renderTaskList();
    showFlash("Список обновлен");
  } catch (error) {
    showFlash("Не удалось обновить список", true);
  }
}

async function deleteCurrentTask() {
  const task = state.tasks.find((item) => item.task_key === state.selectedTaskKey);
  if (!task) return;
  if (!window.confirm(`Удалить задание №${task.task_number} User ${task.user_id}?`)) return;

  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(task.task_key)}`, {
      method: "DELETE",
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      showFlash(data.error || "Не удалось удалить задание", true);
      return;
    }

    state.tasks = state.tasks.filter((item) => item.task_key !== task.task_key);
    const filtered = getFilteredTasks();
    state.selectedTaskKey = filtered[0] ? filtered[0].task_key : null;
    renderStats();
    renderUserFilter();
    renderTaskList();
    showFlash(`Задание №${task.task_number} User ${task.user_id} удалено`);
  } catch (error) {
    showFlash("Не удалось удалить задание", true);
  }
}

function showFlash(text, isError = false) {
  adminFlash.textContent = text;
  adminFlash.classList.toggle("is-error", isError);
  adminFlash.classList.add("visible");
  clearTimeout(showFlash._timer);
  showFlash._timer = setTimeout(() => {
    adminFlash.classList.remove("visible");
  }, 1800);
}

function setActiveFilter(filter) {
  state.filter = filter;
  filterButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.filter === filter);
  });
}

function clearFilters() {
  state.query = "";
  state.userFilter = "";
  setActiveFilter("all");
  adminSearch.value = "";
  adminUserFilter.value = "";
  renderTaskList();
}

function syncMobilePane() {
  const isMobile = window.matchMedia("(max-width: 860px)").matches;
  document.body.classList.toggle("admin_mobile_list", isMobile && state.mobilePane === "list");
  document.body.classList.toggle("admin_mobile_editor", isMobile && state.mobilePane === "editor");
  mobileListBtn.classList.toggle("active", !isMobile || state.mobilePane === "list");
  mobileEditorBtn.classList.toggle("active", isMobile && state.mobilePane === "editor");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

adminSearch.addEventListener("input", () => {
  state.query = adminSearch.value.trim().toLowerCase();
  renderTaskList();
});

adminUserFilter.addEventListener("change", () => {
  state.userFilter = adminUserFilter.value;
  renderTaskList();
});

filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setActiveFilter(button.dataset.filter);
    renderTaskList();
  });
});

prevTaskBtn.addEventListener("click", () => {
  const filtered = getFilteredTasks();
  const index = filtered.findIndex((task) => task.task_key === state.selectedTaskKey);
  if (index > 0) {
    state.selectedTaskKey = filtered[index - 1].task_key;
    state.mobilePane = "editor";
    renderTaskList();
  }
});

nextTaskBtn.addEventListener("click", () => {
  const filtered = getFilteredTasks();
  const index = filtered.findIndex((task) => task.task_key === state.selectedTaskKey);
  if (index !== -1 && index < filtered.length - 1) {
    state.selectedTaskKey = filtered[index + 1].task_key;
    state.mobilePane = "editor";
    renderTaskList();
  }
});

clearFiltersBtn.addEventListener("click", clearFilters);
refreshTasksBtn.addEventListener("click", refreshTasks);
mobileRefreshBtn.addEventListener("click", refreshTasks);
saveAnswerBtnAdmin.addEventListener("click", () => saveCurrentTask({ answer_text: adminAnswerText.value }));
clearAnswerBtn.addEventListener("click", () => {
  adminAnswerText.value = "";
  saveCurrentTask({ answer_text: "" });
});
deleteTaskBtn.addEventListener("click", deleteCurrentTask);
mobileListBtn.addEventListener("click", () => {
  state.mobilePane = "list";
  syncMobilePane();
});
mobileEditorBtn.addEventListener("click", () => {
  state.mobilePane = "editor";
  syncMobilePane();
});

window.addEventListener("resize", syncMobilePane);

state.selectedTaskKey = state.tasks[0] ? state.tasks[0].task_key : null;
renderStats();
renderUserFilter();
renderTaskList();
syncMobilePane();
