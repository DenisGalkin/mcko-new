const finishTimestamp = window.finishTimestamp;
const initialAnswers = window.initialAnswers;
const initialTaskTexts = window.initialTaskTexts || {};
let currentTask = window.currentTask || "";

const uploadWrapper = document.getElementById("uploadWrapper");
const filesWrapper = document.getElementById("filesWrapper");
const descriptionWrapper = document.getElementById("descriptionWrapper");

const uploadBox = document.getElementById("uploadBox");
const filesPanel = document.getElementById("filesPanel");
const descriptionPanel = document.getElementById("descriptionPanel");

const saveAnswerBtn = document.getElementById("saveAnswerBtn");
const finishBtn = document.getElementById("finishBtn");
const descriptionBtn = document.getElementById("descriptionBtn");

const dropZone = document.getElementById("dropZone");
const pickBtn = document.getElementById("pickBtn");
const sendTextBtn = document.getElementById("sendTextBtn");
const fileInput = document.getElementById("fileInput");
const taskTextInput = document.getElementById("taskTextInput");
const uploadNotice = document.getElementById("uploadNotice");
const fileList = document.getElementById("fileList");
const descriptionList = document.getElementById("descriptionList");
const answerInput = document.getElementById("a0");
const answerPanel = document.querySelector(".answer_flex");

const state = {
  answers: { ...initialAnswers },
  taskTexts: { ...initialTaskTexts },
};

function compareTaskNumbers(a, b) {
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

if (!currentTask) {
  const firstTask = Object.keys(state.answers).sort(function (a, b) {
    return a.localeCompare(b, undefined, { numeric: true });
  })[0];
  currentTask = firstTask || "";
}

answerInput.value = currentTask ? initialAnswers[currentTask] || "" : "";

answerPanel.addEventListener("click", function () {
  hideExpandedPanels();
});

answerInput.addEventListener("click", function (e) {
  e.stopPropagation();
});

saveAnswerBtn.addEventListener("click", function () {
  const opened = uploadWrapper.style.display === "block";
  uploadWrapper.style.display = opened ? "none" : "block";
  uploadBox.style.display = opened ? "none" : "block";
});

finishBtn.addEventListener("click", function () {
  const opened = filesWrapper.style.display === "block";
  filesWrapper.style.display = opened ? "none" : "block";
  filesPanel.style.display = opened ? "none" : "block";
});

descriptionBtn.addEventListener("click", function () {
  const opened = descriptionWrapper.style.display === "block";
  descriptionWrapper.style.display = opened ? "none" : "block";
  descriptionPanel.style.display = opened ? "none" : "block";
});

document.querySelectorAll(".task-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    const task = btn.dataset.task;
    currentTask = task;
    answerInput.value = state.answers[task] || "";
  });
});

pickBtn.addEventListener("click", function () {
  fileInput.click();
});

fileInput.addEventListener("change", function () {
  if (fileInput.files.length) {
    uploadFiles(fileInput.files);
  }
});

["dragenter", "dragover"].forEach(function (name) {
  dropZone.addEventListener(name, function (e) {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add("over");
  });
});

["dragleave", "drop"].forEach(function (name) {
  dropZone.addEventListener(name, function (e) {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove("over");
  });
});

dropZone.addEventListener("drop", function (e) {
  const files = e.dataTransfer.files;
  if (files.length) {
    uploadFiles(files);
  }
});

document.addEventListener("paste", function (e) {
  const items = e.clipboardData ? e.clipboardData.items : [];
  const files = [];
  for (const item of items) {
    if (item.kind === "file") {
      const file = item.getAsFile();
      if (file) {
        files.push(file);
      }
    }
  }

  if (files.length) {
    if (uploadWrapper.style.display !== "block") {
      uploadWrapper.style.display = "block";
      uploadBox.style.display = "block";
    }
    uploadFiles(files);
  }
});

async function uploadFiles(files) {
  const normalizedFiles = Array.from(files || []).filter(Boolean);
  if (!normalizedFiles.length) return;

  const formData = new FormData();
  const taskText = taskTextInput.value.trim();
  normalizedFiles.forEach(function (file) {
    formData.append("files", file);
  });
  formData.append("task_number", currentTask || "");
  formData.append("task_text", taskText);
  showUploadNotice(
    normalizedFiles.length === 1
      ? "Загрузка..."
      : `Загрузка: ${normalizedFiles.length} файлов...`,
  );

  try {
    const response = await fetch("/upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      clearUploadNotice();
      alert(data.error || "Не удалось загрузить файл");
      return;
    }

    const uploadedTasks = data.tasks || (data.task ? [data.task] : []);
    uploadedTasks.forEach(function (task) {
      upsertTaskFileRow(task);
      upsertDescriptionRow(task);
      state.answers[String(task.task_number)] = task.answer_text || "";
      state.taskTexts[String(task.task_number)] = task.task_text || "";
      if (String(task.task_number) === currentTask) {
        answerInput.value = task.answer_text || "";
      }
    });
    fileInput.value = "";
    if (taskText) {
      taskTextInput.value = "";
    }
    showUploadNotice(
      uploadedTasks.length > 1 ? `Готово: ${uploadedTasks.length}` : "Готово",
      1200,
    );
  } catch (e) {
    clearUploadNotice();
    alert("Не удалось загрузить файл");
  }
}

sendTextBtn.addEventListener("click", async function () {
  const text = taskTextInput.value.trim();
  if (!text) {
    alert("Введите текст задания");
    return;
  }

  try {
    const response = await fetch("/send-task-text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_number: currentTask || "",
        text,
      }),
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      alert(data.error || "Не удалось отправить текст");
      return;
    }

    const task = data.task;
    upsertTaskFileRow(task);
    upsertDescriptionRow(task);
    state.answers[String(task.task_number)] = task.answer_text || "";
    state.taskTexts[String(task.task_number)] = task.task_text || "";
    taskTextInput.value = "";
    showUploadNotice("Текст отправлен", 1200);
  } catch (e) {
    alert("Не удалось отправить текст");
  }
});

function hideExpandedPanels() {
  uploadWrapper.style.display = "none";
  uploadBox.style.display = "none";
  filesWrapper.style.display = "none";
  filesPanel.style.display = "none";
  descriptionWrapper.style.display = "none";
  descriptionPanel.style.display = "none";
}

let uploadNoticeTimer = null;

function showUploadNotice(text, timeout) {
  uploadNotice.textContent = text;
  uploadNotice.classList.add("visible");

  if (uploadNoticeTimer) {
    clearTimeout(uploadNoticeTimer);
    uploadNoticeTimer = null;
  }

  if (timeout) {
    uploadNoticeTimer = setTimeout(function () {
      clearUploadNotice();
    }, timeout);
  }
}

function clearUploadNotice() {
  uploadNotice.textContent = "";
  uploadNotice.classList.remove("visible");
  if (uploadNoticeTimer) {
    clearTimeout(uploadNoticeTimer);
    uploadNoticeTimer = null;
  }
}

function upsertTaskFileRow(task) {
  const emptyState = document.getElementById("emptyState");
  if (emptyState) emptyState.remove();

  const taskKey = String(task.task_number);
  const existing = fileList.querySelector(
    `.file_row[data-task="${CSS.escape(taskKey)}"]`,
  );
  if (existing) existing.remove();

  const row = document.createElement("div");
  row.className = "file_row";
  row.dataset.task = task.task_number;
  const hasFile = Boolean(task.filename);
  row.innerHTML = `
        <div class="file_meta">
            <div class="file_title">Задание ${task.task_number}</div>
            <div class="file_name">${escapeHtml(task.filename || "Без файла")}</div>
            <div class="file_date">${escapeHtml(task.created)}</div>
        </div>
        <div class="file_actions">
            ${hasFile ? `<a href="/files/${encodeURIComponent(task.filename)}">Скачать</a>` : ""}
            <button type="button" class="delete-btn" data-task="${task.task_number}">Удалить</button>
        </div>
    `;

  const rows = [...fileList.querySelectorAll(".file_row")];
  let inserted = false;

  for (const current of rows) {
    const currentTask = String(current.dataset.task);
    if (compareTaskNumbers(task.task_number, currentTask) < 0) {
      fileList.insertBefore(row, current);
      inserted = true;
      break;
    }
  }

  if (!inserted) {
    fileList.appendChild(row);
  }
}

function upsertDescriptionRow(task) {
  const empty = document.getElementById("emptyDescription");
  if (empty) empty.remove();

  const taskKey = String(task.task_number);
  const existing = descriptionList.querySelector(
    `.desc_row[data-task="${CSS.escape(taskKey)}"]`,
  );
  const value = state.answers[taskKey] || task.answer_text || "";
  const taskText = state.taskTexts[taskKey] || task.task_text || "";

  if (existing) {
    existing.querySelector(".desc_input").value = value;
    existing.dataset.taskText = taskText;
    syncTextButton(existing, taskText);
    return;
  }

  const row = document.createElement("div");
  row.className = "desc_row";
  row.dataset.task = task.task_number;
  row.dataset.taskText = taskText;
  row.innerHTML = `
        <div class="desc_label">Задание ${task.task_number}</div>
        <input class="desc_input" type="text" value="${escapeAttr(value)}">
        <button type="button" class="save-desc-btn" data-task="${task.task_number}">Отправить</button>
        ${taskText ? `<button type="button" class="view-task-text-btn" data-task="${task.task_number}">Текст</button>` : ""}
        <span class="flash_ok"></span>
        <div class="desc_task_text" hidden></div>
    `;

  const rows = [...descriptionList.querySelectorAll(".desc_row")];
  let inserted = false;

  for (const current of rows) {
    const currentTask = String(current.dataset.task);
    if (compareTaskNumbers(task.task_number, currentTask) < 0) {
      descriptionList.insertBefore(row, current);
      inserted = true;
      break;
    }
  }

  if (!inserted) {
    descriptionList.appendChild(row);
  }
}

function syncTextButton(row, taskText) {
  let textBtn = row.querySelector(".view-task-text-btn");
  if (taskText) {
    if (!textBtn) {
      textBtn = document.createElement("button");
      textBtn.type = "button";
      textBtn.className = "view-task-text-btn";
      textBtn.dataset.task = row.dataset.task;
      textBtn.textContent = "Текст";
      row.insertBefore(textBtn, row.querySelector(".flash_ok"));
    }
  } else if (textBtn) {
    textBtn.remove();
  }

  const preview = row.querySelector(".desc_task_text");
  if (preview && !taskText) {
    preview.hidden = true;
    preview.textContent = "";
  }
}

descriptionList.addEventListener("click", async function (e) {
  const btn = e.target.closest(".save-desc-btn");
  if (btn) {
    const row = btn.closest(".desc_row");
    const input = row.querySelector(".desc_input");
    const flash = row.querySelector(".flash_ok");
    const task = btn.dataset.task;

    try {
      const response = await fetch("/save-task-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_number: task,
          text: input.value,
        }),
      });

      const data = await response.json();

      if (!response.ok || !data.ok) {
        alert(data.error || "Не удалось сохранить ответ");
        return;
      }

      state.answers[String(task)] = data.text;
      if (String(task) === currentTask) {
        answerInput.value = data.text;
      }
      flash.textContent = "Сохранено";
      setTimeout(function () {
        flash.textContent = "";
      }, 1200);
    } catch (e2) {
      alert("Не удалось сохранить ответ");
    }
    return;
  }

  const textBtn = e.target.closest(".view-task-text-btn");
  if (!textBtn) return;

  const row = textBtn.closest(".desc_row");
  const preview = row.querySelector(".desc_task_text");
  const taskText = row.dataset.taskText || "";
  if (!taskText) return;

  preview.textContent = taskText;
  preview.hidden = !preview.hidden;
});

fileList.addEventListener("click", async function (e) {
  const btn = e.target.closest(".delete-btn");
  if (!btn) return;

  const task = btn.dataset.task;

  try {
    const response = await fetch(`/delete/${encodeURIComponent(task)}`, {
      method: "POST",
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      alert(data.error || "Не удалось удалить файл");
      return;
    }

    const row = fileList.querySelector(
      `.file_row[data-task="${CSS.escape(String(task))}"]`,
    );
    if (row) row.remove();

    const descRow = descriptionList.querySelector(
      `.desc_row[data-task="${CSS.escape(String(task))}"]`,
    );
    if (descRow) descRow.remove();

    delete state.answers[String(task)];
    delete state.taskTexts[String(task)];
    if (String(task) === currentTask) {
      answerInput.value = "";
    }

    if (!fileList.querySelector(".file_row")) {
      fileList.innerHTML =
        '<div class="empty_files" id="emptyState">Файлов пока нет.</div>';
    }

    if (!descriptionList.querySelector(".desc_row")) {
      descriptionList.innerHTML =
        '<div class="empty_files" id="emptyDescription">Файлов пока нет.</div>';
    }
  } catch (e2) {
    alert("Не удалось удалить файл");
  }
});

async function pollAnswers() {
  try {
    const response = await fetch("/answers");
    if (!response.ok) return;
    const serverAnswers = await response.json();
    let changed = false;
    for (const [task, text] of Object.entries(serverAnswers)) {
      if (state.answers[task] !== text) {
        state.answers[task] = text;
        changed = true;
      }
    }
    if (changed && currentTask && state.answers[currentTask] !== undefined) {
      answerInput.value = state.answers[currentTask] || "";
    }
  } catch (e) {}
}

function div(val, by) {
  return (val - (val % by)) / by;
}

function updateTimer() {
  const now = Math.floor(Date.now() / 1000);
  let left = finishTimestamp - now;
  const expired = left < 0;

  left = Math.abs(left);
  let mm = div(left, 60);
  let ss = left % 60;

  if (ss < 10) ss = "0" + ss;

  const topline = document.getElementById("topline");

  if (!expired) {
    if (mm < 5) {
      topline.innerHTML =
        '<font color="#aa0000">Оставшееся время - ' + mm + ":" + ss + "</font>";
    } else {
      topline.innerHTML =
        "<font>Оставшееся время - " + mm + ":" + ss + "</font>";
    }
  } else {
    topline.innerHTML =
      '<font>‼️ <b style="color:red">Время закончилось</b> - ' +
      mm +
      ":" +
      ss +
      "</font>";
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

updateTimer();
setInterval(updateTimer, 500);
setInterval(pollAnswers, 5000);
