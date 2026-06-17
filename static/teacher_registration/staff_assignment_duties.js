// Grouped teaching-duty editor for the staff school-assignment form.
//
// Mirror of the registration duty-group add/remove logic in
// teacher_registration.js (initializeDutyFormset), adapted for a single
// embedded editor that submits with the assignment form (no modal, no AJAX).
// Adds/removes "class level" groups, each a year-level select + multi-subject
// select, named duties[i][year_level] / duties[i][subjects][].
//
// Primary teachers claim class levels only: when the teacher level select is
// Primary the subjects column is hidden (and its select made non-required) and
// the year-level column expands to full width. JSS/SSS keep both columns.
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var container = document.getElementById('duty-groups');
    var template = document.getElementById('empty-duty-group');
    var addBtn = document.querySelector('.add-duty-group');
    if (!container || !template || !addBtn) return;

    var levelSelect = document.getElementById('id_teacher_level_type');

    function isPrimaryLevel() {
      if (!levelSelect) return false;
      var opt = levelSelect.options[levelSelect.selectedIndex];
      return (opt && opt.text ? opt.text.toLowerCase() : '').includes('primary');
    }

    // Show/hide the subjects column of one group for the current level.
    function applyLevelToGroup(group, primary) {
      var yearCol = group.querySelector('.duty-year-col');
      var subjectsCol = group.querySelector('.duty-subjects-col');
      if (yearCol) {
        yearCol.classList.toggle('col-md-12', primary);
        yearCol.classList.toggle('col-md-5', !primary);
      }
      if (subjectsCol) {
        subjectsCol.classList.toggle('d-none', primary);
        var subjectsSelect = subjectsCol.querySelector('select');
        if (subjectsSelect) {
          subjectsSelect.required = !primary;
          // A hidden required control would block form submission.
          if (primary) subjectsSelect.removeAttribute('required');
        }
      }
    }

    function applyLevelToAll() {
      var primary = isPrimaryLevel();
      container.querySelectorAll('.duty-group').forEach(function (group) {
        applyLevelToGroup(group, primary);
      });
      var hint = document.querySelector('.duty-subjects-hint');
      if (hint) hint.classList.toggle('d-none', primary);
    }

    // Add a new class-level group
    addBtn.addEventListener('click', function (e) {
      e.preventDefault();

      var noMsg = document.getElementById('no-duties-msg');
      if (noMsg) noMsg.remove();

      var nextIndex = container.querySelectorAll('.duty-group').length;

      var templateContent = template.content.firstElementChild.cloneNode(true);
      var tempDiv = document.createElement('div');
      tempDiv.appendChild(templateContent);
      tempDiv.innerHTML = tempDiv.innerHTML.split('__INDEX__').join(nextIndex);
      var newGroup = tempDiv.firstElementChild;

      container.appendChild(newGroup);
      applyLevelToGroup(newGroup, isPrimaryLevel());
      newGroup.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });

    // Remove a class-level group, then re-index the remaining ones
    container.addEventListener('click', function (e) {
      var removeBtn = e.target.closest('.remove-duty-group');
      if (!removeBtn) return;
      e.preventDefault();

      var group = removeBtn.closest('.duty-group');
      if (!group) return;
      group.remove();

      container.querySelectorAll('.duty-group').forEach(function (g, index) {
        g.querySelectorAll('select').forEach(function (sel) {
          sel.name = sel.name.replace(/duties\[\d+\]/, 'duties[' + index + ']');
        });
      });
    });

    if (levelSelect) levelSelect.addEventListener('change', applyLevelToAll);
    applyLevelToAll();
  });
})();
