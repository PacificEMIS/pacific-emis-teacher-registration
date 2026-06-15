// Grouped teaching-duty editor for the staff school-assignment form.
//
// Mirror of the registration duty-group add/remove logic in
// teacher_registration.js (initializeDutyFormset), adapted for a single
// embedded editor that submits with the assignment form (no modal, no AJAX).
// Adds/removes "class level" groups, each a year-level select + multi-subject
// select, named duties[i][year_level] / duties[i][subjects][].
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var container = document.getElementById('duty-groups');
    var template = document.getElementById('empty-duty-group');
    var addBtn = document.querySelector('.add-duty-group');
    if (!container || !template || !addBtn) return;

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
  });
})();
