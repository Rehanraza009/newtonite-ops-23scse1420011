/**
 * Newtonite Operations Hub - Client Application Logic
 */

// CSRF Cookie extraction helper
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

const CSRF_TOKEN = getCookie('csrftoken');

// Global Notification Banner
function showAlert(message, type = 'error') {
  let container = document.getElementById('global-alert-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'global-alert-container';
    container.style.position = 'fixed';
    container.style.top = '70px';
    container.style.right = '20px';
    container.style.zIndex = '9999';
    container.style.maxWidth = '450px';
    document.body.appendChild(container);
  }

  const alertBox = document.createElement('div');
  alertBox.className = `alert alert-${type}`;
  alertBox.style.boxShadow = 'var(--shadow-lg)';
  alertBox.style.marginBottom = '10px';
  alertBox.innerHTML = `
    <span>${message}</span>
    <button type="button" style="background:none; border:none; color:inherit; font-size:1.1rem; cursor:pointer; margin-left:10px;" onclick="this.parentElement.remove()">&times;</button>
  `;
  container.appendChild(alertBox);

  setTimeout(() => {
    if (alertBox.parentElement) alertBox.remove();
  }, 6000);
}

// ============================================================================
// CLAIM ACTION HANDLER
// ============================================================================
async function claimWorkItem(itemId, buttonElement) {
  if (buttonElement) {
    buttonElement.disabled = true;
    buttonElement.innerText = "Claiming...";
  }

  try {
    const response = await fetch(`/api/items/${itemId}/claim/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CSRF_TOKEN,
      },
    });

    const data = await response.json();

    if (response.ok) {
      showAlert(`Successfully claimed item #${itemId}!`, 'success');
      setTimeout(() => window.location.reload(), 600);
    } else if (response.status === 409) {
      // Concurrency conflict: already claimed by another user
      showAlert(`Conflict: ${data.message || 'Work item was already claimed by another user.'}`, 'conflict');
      setTimeout(() => window.location.reload(), 1500);
    } else if (response.status === 403) {
      showAlert(`Forbidden: ${data.message || 'You lack permission to claim items in this team.'}`, 'error');
      if (buttonElement) {
        buttonElement.disabled = false;
        buttonElement.innerText = "Claim Item";
      }
    } else {
      showAlert(`Error: ${data.message || 'Could not claim item.'}`, 'error');
      if (buttonElement) {
        buttonElement.disabled = false;
        buttonElement.innerText = "Claim Item";
      }
    }
  } catch (err) {
    showAlert(`Network error: ${err.message}`, 'error');
    if (buttonElement) {
      buttonElement.disabled = false;
      buttonElement.innerText = "Claim Item";
    }
  }
}

// ============================================================================
// TRANSITION ACTION HANDLER
// ============================================================================
let currentTransitionItem = null;
let currentTransitionTarget = null;

function openTransitionModal(itemId, targetStatus, targetLabel) {
  currentTransitionItem = itemId;
  currentTransitionTarget = targetStatus;

  const modal = document.getElementById('transition-modal');
  const targetLabelEl = document.getElementById('modal-transition-target');
  const noteEl = document.getElementById('modal-transition-note');

  if (targetLabelEl) targetLabelEl.innerText = targetLabel || targetStatus;
  if (noteEl) noteEl.value = '';
  if (modal) modal.style.display = 'flex';
}

function closeTransitionModal() {
  const modal = document.getElementById('transition-modal');
  if (modal) modal.style.display = 'none';
  currentTransitionItem = null;
  currentTransitionTarget = null;
}

async function confirmTransition() {
  if (!currentTransitionItem || !currentTransitionTarget) return;

  const noteEl = document.getElementById('modal-transition-note');
  const note = noteEl ? noteEl.value.trim() : '';
  const confirmBtn = document.getElementById('modal-transition-submit-btn');

  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.innerText = "Transitioning...";
  }

  try {
    const response = await fetch(`/api/items/${currentTransitionItem}/transition/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CSRF_TOKEN,
      },
      body: JSON.stringify({
        target_status: currentTransitionTarget,
        note: note,
      }),
    });

    const data = await response.json();

    if (response.ok) {
      showAlert(`Status transitioned to ${currentTransitionTarget.replace('_', ' ').toUpperCase()}!`, 'success');
      closeTransitionModal();
      setTimeout(() => window.location.reload(), 600);
    } else if (response.status === 403) {
      showAlert(`Permission Denied: ${data.message || 'Only team Lead/Admin can perform this transition.'}`, 'error');
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.innerText = "Confirm";
      }
    } else {
      showAlert(`Error: ${data.message || 'Transition rejected.'}`, 'error');
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.innerText = "Confirm";
      }
    }
  } catch (err) {
    showAlert(`Network error: ${err.message}`, 'error');
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.innerText = "Confirm";
    }
  }
}

// ============================================================================
// COMMENT POST HANDLER
// ============================================================================
async function postComment(itemId) {
  const inputEl = document.getElementById('comment-input');
  if (!inputEl) return;
  const content = inputEl.value.trim();
  if (!content) return;

  const submitBtn = document.getElementById('comment-submit-btn');
  if (submitBtn) submitBtn.disabled = true;

  try {
    const response = await fetch(`/api/items/${itemId}/comments/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CSRF_TOKEN,
      },
      body: JSON.stringify({ content: content }),
    });

    const data = await response.json();
    if (response.ok) {
      inputEl.value = '';
      showAlert("Comment posted.", "success");
      setTimeout(() => window.location.reload(), 500);
    } else {
      showAlert(`Error: ${data.message || 'Failed to post comment.'}`, 'error');
    }
  } catch (err) {
    showAlert(`Network error: ${err.message}`, 'error');
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

// ============================================================================
// WORK ITEM EDIT FORM WITH OPTIMISTIC CONFLICT HANDLING
// ============================================================================
async function handleItemUpdate(event, itemId) {
  event.preventDefault();
  const form = event.target;
  const submitBtn = form.querySelector('button[type="submit"]');

  const title = form.elements['title'].value.trim();
  const description = form.elements['description'].value.trim();
  const priority = form.elements['priority'].value;
  const type = form.elements['type'].value;
  const assigneeId = form.elements['assignee_id'].value || null;
  const dueDate = form.elements['due_date'].value || null;
  const version = parseInt(form.elements['version'].value, 10);

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerText = "Saving changes...";
  }

  try {
    const response = await fetch(`/api/items/${itemId}/`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CSRF_TOKEN,
        'If-Match': `"${version}"`,
      },
      body: JSON.stringify({
        title,
        description,
        priority,
        type,
        assignee_id: assigneeId,
        due_date: dueDate,
        version: version,
      }),
    });

    const data = await response.json();

    if (response.ok) {
      showAlert("Work item updated successfully!", "success");
      setTimeout(() => {
        window.location.href = `/items/${itemId}/`;
      }, 600);
    } else if (response.status === 409) {
      // Stale update conflict!
      showConflictModal(data);
    } else if (response.status === 403) {
      showAlert(`Forbidden: ${data.message || 'You cannot edit this item.'}`, 'error');
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerText = "Save Changes";
      }
    } else {
      showAlert(`Validation Error: ${JSON.stringify(data)}`, 'error');
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerText = "Save Changes";
      }
    }
  } catch (err) {
    showAlert(`Network error: ${err.message}`, 'error');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerText = "Save Changes";
    }
  }
}

function showConflictModal(conflictData) {
  let modal = document.getElementById('conflict-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'conflict-modal';
    modal.className = 'modal-backdrop';
    document.body.appendChild(modal);
  }

  modal.innerHTML = `
    <div class="modal-container">
      <div class="modal-header" style="background-color: var(--color-warning-subtle); border-bottom-color: var(--color-warning);">
        <h3 class="modal-title" style="color: var(--color-warning-text); font-size:1rem; font-weight:700;">
          ⚠️ Optimistic Lock Conflict (HTTP 409)
        </h3>
      </div>
      <div class="modal-body">
        <p style="margin-bottom:0.75rem; color:var(--text-primary); font-size:0.9rem;">
          ${conflictData.message || 'This record was modified by another operator while you were viewing it.'}
        </p>
        <div style="background-color:var(--bg-body); padding:0.75rem; border-radius:var(--radius-md); font-size:0.8rem; margin-bottom:1rem; border:1px solid var(--border-default);">
          <div><strong>Current Database Version:</strong> ${conflictData.current_version}</div>
          <div style="margin-top:0.25rem;"><strong>Latest Title:</strong> ${conflictData.latest_data?.title || 'N/A'}</div>
          <div><strong>Latest Status:</strong> ${conflictData.latest_data?.status || 'N/A'}</div>
          <div><strong>Latest Priority:</strong> ${conflictData.latest_data?.priority || 'N/A'}</div>
        </div>
        <p style="font-size:0.8rem; color:var(--text-secondary);">
          Your local changes were not overwritten to preserve data integrity. Would you like to reload the latest database version?
        </p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="document.getElementById('conflict-modal').style.display='none'">Dismiss & Review</button>
        <button class="btn btn-primary" onclick="window.location.reload()">Reload Latest Data</button>
      </div>
    </div>
  `;
  modal.style.display = 'flex';
}
