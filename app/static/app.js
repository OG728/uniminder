async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || res.statusText || "Request failed");
  }
  return data;
}

function qs(sel, root = document) {
  return root.querySelector(sel);
}

function qsa(sel, root = document) {
  return [...root.querySelectorAll(sel)];
}

const syncBtn = qs("#sync-btn");
const syncStatus = qs("#sync-status");
const lastSync = qs("#last-sync");

if (syncBtn) {
  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    syncStatus.textContent = "Syncing…";
    try {
      const data = await postJson("/api/sync", {});
      const counts = data.stats || {};
      syncStatus.textContent = `Synced ${counts.courses ?? 0} courses, ${counts.assignments ?? 0} assignments`;
      if (data.last_sync && lastSync) {
        lastSync.textContent = `Last sync: ${data.last_sync}`;
      }
      setTimeout(() => window.location.reload(), 600);
    } catch (err) {
      syncStatus.textContent = err.message;
      syncBtn.disabled = false;
    }
  });
}

qsa(".toggle-done").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const id = btn.dataset.id;
    const currentlyDone = btn.dataset.done === "true";
    btn.disabled = true;
    try {
      await postJson(`/api/assignments/${id}/override`, { done: !currentlyDone });
      window.location.reload();
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
    }
  });
});

const planForm = qs("#plan-form");
if (planForm) {
  planForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const assignmentId = planForm.dataset.assignmentId;
    const fd = new FormData(planForm);
    const body = {
      hours_available: Number(fd.get("hours_available")),
      session_minutes: Number(fd.get("session_minutes")),
    };
    const submit = planForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    submit.textContent = "Generating…";
    try {
      await postJson(`/api/assignments/${assignmentId}/plan`, body);
      window.location.reload();
    } catch (err) {
      alert(err.message);
      submit.disabled = false;
      submit.textContent = "Generate plan";
    }
  });
}

qsa(".toggle-block").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const blockId = btn.dataset.blockId;
    const current = btn.dataset.status;
    const next = current === "done" ? "pending" : "done";
    const body = new URLSearchParams({ status: next });
    btn.disabled = true;
    try {
      const res = await fetch(`/api/blocks/${blockId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to update block");
      }
      window.location.reload();
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
    }
  });
});
