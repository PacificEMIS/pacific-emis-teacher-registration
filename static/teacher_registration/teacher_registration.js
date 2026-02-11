/**
 * Teacher Registration Form JavaScript
 *
 * Handles interactive functionality for the teacher registration form including:
 * - Bootstrap tooltip initialization
 * - Teacher category toggle (New vs Current teacher)
 * - Teacher level type conditional fields (Primary vs JSS/SSS)
 * - Education completion checkbox handler
 * - Dynamic formset management (add/remove rows)
 * - Business address auto-expand
 * - Duties modal AJAX handlers
 */

document.addEventListener('DOMContentLoaded', function() {
  // =========================================================================
  // Initialize Bootstrap Tooltips
  // =========================================================================
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });

  // =========================================================================
  // Teacher Category Toggle - Show/hide Teaching Details for Current teachers
  // =========================================================================
  const teacherCategoryInputs = document.querySelectorAll('input[name="teacher_category"]');
  const teachingDetailsSection = document.getElementById('teaching-details-section');

  function updateTeacherCategorySections() {
    const selectedValue = document.querySelector('input[name="teacher_category"]:checked')?.value;

    if (selectedValue === 'current') {
      // Current teacher - show teaching details section
      teachingDetailsSection?.classList.add('show');
      if (teachingDetailsSection) teachingDetailsSection.style.display = 'block';
    } else {
      // New teacher - hide teaching details section
      teachingDetailsSection?.classList.remove('show');
      if (teachingDetailsSection) teachingDetailsSection.style.display = 'none';
    }
  }

  teacherCategoryInputs.forEach(input => {
    input.addEventListener('change', updateTeacherCategorySections);
  });

  // Initial state
  updateTeacherCategorySections();

  // =========================================================================
  // Teacher Level Type Toggle - Show/hide class_type and duties sections
  // =========================================================================
  function updateTeacherLevelFields(appointmentRow) {
    const levelSelect = appointmentRow.querySelector('[name$="-teacher_level_type"]');
    const classTypeField = appointmentRow.querySelector('.class-type-field');
    const dutiesSection = appointmentRow.querySelector('.claimed-duties-section');

    if (!levelSelect) return;

    const selectedOption = levelSelect.options[levelSelect.selectedIndex];
    const selectedText = selectedOption?.text?.toLowerCase() || '';

    // Show class_type for Primary, show duties for JSS/SSS
    if (selectedText.includes('primary')) {
      classTypeField?.style.setProperty('display', 'block');
      dutiesSection?.style.setProperty('display', 'none');
    } else if (selectedText.includes('jss') || selectedText.includes('sss') || selectedText.includes('secondary')) {
      classTypeField?.style.setProperty('display', 'none');
      dutiesSection?.style.setProperty('display', 'block');
    } else {
      classTypeField?.style.setProperty('display', 'none');
      dutiesSection?.style.setProperty('display', 'none');
    }
  }

  // Bind change events to existing appointment rows
  document.querySelectorAll('.appointment-row').forEach(row => {
    const levelSelect = row.querySelector('[name$="-teacher_level_type"]');
    if (levelSelect) {
      levelSelect.addEventListener('change', () => updateTeacherLevelFields(row));
      // Initial state
      updateTeacherLevelFields(row);
    }
  });

  // =========================================================================
  // Completed Checkbox Toggle - Show/hide percentage_progress field
  // =========================================================================
  function updateCompletedFields(educationRow) {
    const completedCheckbox = educationRow.querySelector('[name$="-completed"]');
    const progressField = educationRow.querySelector('.progress-field');

    if (completedCheckbox && progressField) {
      if (completedCheckbox.checked) {
        progressField.style.display = 'none';
      } else {
        progressField.style.display = 'block';
      }
    }
  }

  // Bind change events to existing education rows
  document.querySelectorAll('.education-row').forEach(row => {
    const completedCheckbox = row.querySelector('[name$="-completed"]');
    if (completedCheckbox) {
      completedCheckbox.addEventListener('change', () => updateCompletedFields(row));
      // Initial state
      updateCompletedFields(row);
    }
  });

  // =========================================================================
  // Formset Management - Add/Remove rows
  // =========================================================================
  function getFormsetInfo(formsetType) {
    const config = {
      'education': {
        container: '#education-formset',
        prefix: 'education_records',
        rowClass: 'education-row',
        badgeClass: 'bg-secondary',
        badgeText: 'Education'
      },
      'training': {
        container: '#training-formset',
        prefix: 'training_records',
        rowClass: 'training-row',
        badgeClass: 'bg-info',
        badgeText: 'Training'
      },
      'appointment': {
        container: '#appointment-formset',
        prefix: 'claimed_appointments',
        rowClass: 'appointment-row',
        badgeClass: 'bg-success',
        badgeText: 'School Appointment'
      }
    };
    return config[formsetType];
  }

  // Add new formset row
  document.querySelectorAll('.add-formset-row').forEach(button => {
    button.addEventListener('click', function() {
      const formsetType = this.dataset.formset;
      const info = getFormsetInfo(formsetType);
      if (!info) return;

      const container = document.querySelector(info.container);
      const totalFormsInput = document.querySelector(`#id_${info.prefix}-TOTAL_FORMS`);

      if (!container || !totalFormsInput) return;

      const currentCount = parseInt(totalFormsInput.value);

      // Clone the last row or create a new empty one
      const existingRows = container.querySelectorAll(`.${info.rowClass}`);
      let newRow;

      if (existingRows.length > 0) {
        newRow = existingRows[existingRows.length - 1].cloneNode(true);
        // Clear input values
        newRow.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]), select, textarea').forEach(input => {
          if (input.type === 'checkbox') {
            input.checked = input.name.includes('completed');
          } else {
            input.value = '';
          }
        });
        // Clear the ID field (this is a new record)
        const idInput = newRow.querySelector('input[name$="-id"]');
        if (idInput) idInput.value = '';
        // Uncheck DELETE
        const deleteInput = newRow.querySelector('input[name$="-DELETE"]');
        if (deleteInput) deleteInput.checked = false;
      } else {
        // Create a minimal new row structure - this is a fallback
        newRow = document.createElement('div');
        newRow.className = `formset-row ${info.rowClass} mt-3`;
        newRow.innerHTML = `<p class="text-muted">Please reload the page to add more records.</p>`;
      }

      // Update all field names/ids with new index
      newRow.querySelectorAll('[name], [id]').forEach(element => {
        if (element.name) {
          element.name = element.name.replace(/-\d+-/, `-${currentCount}-`);
        }
        if (element.id) {
          element.id = element.id.replace(/-\d+-/, `-${currentCount}-`);
        }
      });

      // Update badge number
      const badge = newRow.querySelector('.badge');
      if (badge) {
        badge.textContent = `${info.badgeText} #${currentCount + 1}`;
      }

      // Remove to-delete class if present
      newRow.classList.remove('to-delete');

      // Append and update count
      container.appendChild(newRow);
      totalFormsInput.value = currentCount + 1;

      // Rebind event handlers
      bindRemoveButtons();

      // For education rows, bind completed checkbox
      if (formsetType === 'education') {
        const completedCheckbox = newRow.querySelector('[name$="-completed"]');
        if (completedCheckbox) {
          completedCheckbox.addEventListener('change', () => updateCompletedFields(newRow));
          updateCompletedFields(newRow);
        }
      }

      // For appointment rows, bind teacher level select
      if (formsetType === 'appointment') {
        const levelSelect = newRow.querySelector('[name$="-teacher_level_type"]');
        if (levelSelect) {
          levelSelect.addEventListener('change', () => updateTeacherLevelFields(newRow));
          updateTeacherLevelFields(newRow);
        }
      }
    });
  });

  // Remove formset row
  function bindRemoveButtons() {
    document.querySelectorAll('.remove-formset-row').forEach(button => {
      button.onclick = function() {
        const row = this.closest('.formset-row');
        const deleteInput = row.querySelector('input[name$="-DELETE"]');
        const idInput = row.querySelector('input[name$="-id"]');

        if (idInput && idInput.value) {
          // Existing record - mark for deletion
          deleteInput.checked = true;
          row.classList.add('to-delete');
        } else {
          // New record - just remove from DOM
          row.remove();

          // Update total forms count - determine formset type from row class
          let formsetPrefix = null;
          if (row.classList.contains('education-row')) {
            formsetPrefix = 'education_records';
          } else if (row.classList.contains('training-row')) {
            formsetPrefix = 'training_records';
          } else if (row.classList.contains('appointment-row')) {
            formsetPrefix = 'claimed_appointments';
          }

          if (formsetPrefix) {
            const totalFormsInput = document.querySelector(`#id_${formsetPrefix}-TOTAL_FORMS`);
            if (totalFormsInput) {
              totalFormsInput.value = Math.max(0, parseInt(totalFormsInput.value) - 1);
            }
          }
        }
      };
    });
  }

  // Initial bind
  bindRemoveButtons();

  // =========================================================================
  // Business Address - Auto-expand if has content
  // =========================================================================
  const businessAddressInput = document.getElementById('id_business_address');
  const hasBusinessAddress = businessAddressInput && businessAddressInput.value.trim() !== '';

  if (hasBusinessAddress) {
    const businessCollapse = document.getElementById('businessAddress');
    if (businessCollapse) {
      businessCollapse.classList.add('show');
    }
  }

  // =========================================================================
  // Duties Modal - Load and Save
  // =========================================================================
  const dutiesModal = document.getElementById('dutiesModal');
  const dutiesModalBody = document.getElementById('dutiesModalBody');
  const saveDutiesBtn = document.getElementById('saveDutiesBtn');
  let currentAppointmentId = null;

  // Function to initialize duty formset handlers after AJAX load
  function initializeDutyFormset(appointmentId) {
    console.log('Initializing grouped duty formset for appointment:', appointmentId);

    const groupsContainer = document.getElementById('duty-groups-' + appointmentId);
    const emptyGroupTemplate = document.getElementById('empty-duty-group-' + appointmentId);
    const addButton = document.querySelector('.add-duty-group[data-appointment="' + appointmentId + '"]');

    // Debug: Check if elements exist
    if (!groupsContainer) {
      console.error('Groups container not found!');
      return;
    }
    if (!emptyGroupTemplate) {
      console.error('Empty group template not found!');
      return;
    }
    if (!addButton) {
      console.error('Add button not found!');
      return;
    }

    console.log('Grouped duty formset initialized successfully for appointment ' + appointmentId);

    // Handle add duty group
    addButton.onclick = function(e) {
      e.preventDefault();
      e.stopPropagation();

      console.log('Add duty group button clicked!');

      // Remove "no duties" message if it exists
      const noMsg = document.getElementById('no-duties-msg-' + appointmentId);
      if (noMsg) {
        noMsg.remove();
      }

      // Count existing groups to get next index
      const existingGroups = groupsContainer.querySelectorAll('.duty-group');
      const nextIndex = existingGroups.length;

      console.log('Next index:', nextIndex);

      // Clone from the <template> element's content
      const templateContent = emptyGroupTemplate.content.firstElementChild.cloneNode(true);

      // Replace __INDEX__ with actual index in the entire HTML
      const tempDiv = document.createElement('div');
      tempDiv.appendChild(templateContent);
      tempDiv.innerHTML = tempDiv.innerHTML.split('__INDEX__').join(nextIndex);
      const newGroup = tempDiv.firstElementChild;

      // Append to container
      groupsContainer.appendChild(newGroup);
      // Scroll the new group into view
      newGroup.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      console.log('Added new group');

      return false;
    };

    // Handle remove duty group - attach to the groups container
    groupsContainer.addEventListener('click', function(e) {
      const removeBtn = e.target.closest('.remove-duty-group');
      if (!removeBtn) return;

      e.preventDefault();
      e.stopPropagation();

      console.log('Remove group button clicked!');

      const group = removeBtn.closest('.duty-group');
      if (!group) return;

      // Just remove the group
      group.remove();
      console.log('Group removed');

      // Re-index remaining groups
      const remainingGroups = groupsContainer.querySelectorAll('.duty-group');
      remainingGroups.forEach((group, index) => {
        // Update all name attributes to have correct indices
        const selects = group.querySelectorAll('select');
        selects.forEach(select => {
          const name = select.name;
          // Replace the index in the name (e.g., duties[0][...] -> duties[newIndex][...])
          select.name = name.replace(/duties\[\d+\]/, `duties[${index}]`);
        });
      });

      console.log('Groups re-indexed');
    });

    console.log('Event handlers attached');
  }

  // Load duties formset when modal opens
  dutiesModal.addEventListener('show.bs.modal', function(event) {
    const button = event.relatedTarget;
    currentAppointmentId = button.getAttribute('data-appointment-id');

    // Show loading spinner
    dutiesModalBody.innerHTML = `
      <div class="text-center py-5">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
      </div>
    `;

    // Load formset via AJAX
    fetch(`/registration/appointments/${currentAppointmentId}/duties/`)
      .then(response => response.text())
      .then(html => {
        dutiesModalBody.innerHTML = html;
        // Initialize duty formset handlers after content is loaded
        initializeDutyFormset(currentAppointmentId);
      })
      .catch(error => {
        console.error('Error loading duties:', error);
        dutiesModalBody.innerHTML = `
          <div class="alert alert-danger">
            <i class="bi bi-exclamation-triangle me-1"></i>
            Failed to load duties. Please try again.
          </div>
        `;
      });
  });

  // Save duties via AJAX
  saveDutiesBtn.addEventListener('click', function() {
    if (!currentAppointmentId) return;

    const form = document.getElementById(`duty-form-${currentAppointmentId}`);
    if (!form) return;

    // Build FormData explicitly from duty groups to ensure dynamically-added
    // elements are captured reliably across all browsers.
    const formData = new FormData();

    // Add CSRF token
    const csrfInput = form.querySelector('[name=csrfmiddlewaretoken]');
    if (csrfInput) {
      formData.append('csrfmiddlewaretoken', csrfInput.value);
    }

    // Collect data from each duty group, skipping empty/incomplete cards
    const groupsContainer = document.getElementById(`duty-groups-${currentAppointmentId}`);
    const groups = groupsContainer.querySelectorAll('.duty-group');

    let dataIndex = 0;
    groups.forEach((group) => {
      const yearLevelSelect = group.querySelector('.year-level-select');
      const subjectsSelect = group.querySelector('.subjects-select');
      const ylValue = yearLevelSelect ? yearLevelSelect.value : '';
      const selectedSubjects = subjectsSelect ? Array.from(subjectsSelect.selectedOptions) : [];

      // Skip cards with no year level or no subjects selected
      if (!ylValue || selectedSubjects.length === 0) return;

      formData.append(`duties[${dataIndex}][year_level]`, ylValue);
      selectedSubjects.forEach(option => {
        formData.append(`duties[${dataIndex}][subjects][]`, option.value);
      });
      dataIndex++;
    });

    // Disable save button
    saveDutiesBtn.disabled = true;
    saveDutiesBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';

    fetch(form.action, {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
      },
    })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          // Update duties list in the main form
          const dutiesListContainer = document.getElementById(`duties-list-${currentAppointmentId}`);
          if (dutiesListContainer) {
            dutiesListContainer.innerHTML = data.duties_html;
          }

          // Close modal
          const modalInstance = bootstrap.Modal.getInstance(dutiesModal);
          modalInstance.hide();

          // Show success message
          const alertHtml = `
            <div class="alert alert-success alert-dismissible fade show" role="alert">
              <i class="bi bi-check-circle me-1"></i>
              ${data.message}
              <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
          `;
          const messagesContainer = document.querySelector('.messages-container');
          if (messagesContainer) {
            messagesContainer.innerHTML = alertHtml + messagesContainer.innerHTML;
          }
        } else {
          // Show error
          const errorMsg = data.errors ? data.errors.join(', ') : data.error;
          dutiesModalBody.insertAdjacentHTML('afterbegin', `
            <div class="alert alert-danger alert-dismissible fade show">
              <i class="bi bi-exclamation-triangle me-1"></i>
              ${errorMsg}
              <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
          `);
        }
      })
      .catch(error => {
        console.error('Error saving duties:', error);
        dutiesModalBody.insertAdjacentHTML('afterbegin', `
          <div class="alert alert-danger alert-dismissible fade show">
            <i class="bi bi-exclamation-triangle me-1"></i>
            Failed to save duties. Please try again.
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        `);
      })
      .finally(() => {
        // Re-enable save button
        saveDutiesBtn.disabled = false;
        saveDutiesBtn.innerHTML = '<i class="bi bi-check-circle me-1"></i> Save Duties';
      });
  });
});
