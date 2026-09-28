'use strict';
document.querySelectorAll('input[name="evidence_ids"]').forEach(input => {
  input.addEventListener('change', () => {
    const selected = new Set([...document.querySelectorAll('input[name="evidence_ids"]:checked:not(:disabled)')].map(item => item.value));
    document.querySelectorAll('input[name="skill_names"]').forEach(skill => {
      const eligible = skill.dataset.confirmed === 'true' || JSON.parse(skill.dataset.evidenceIds).some(id => selected.has(id));
      const status = skill.closest('label').querySelector('[data-skill-status]');
      if (!eligible) skill.checked = false;
      status.textContent = eligible ? '' : '需先选择关联证据，或在技能库确认。';
      skill.disabled = !eligible;
      const description = skill.closest('li').querySelector('[data-skill-description]');
      if (description) description.disabled = !eligible;
    });
  });
});

const descriptionPayload = document.querySelector('[name="skill_desc_payload"]');
if (descriptionPayload) descriptionPayload.form.addEventListener('submit', () => {
  descriptionPayload.value = JSON.stringify(Object.fromEntries(
    [...document.querySelectorAll('input[name="skill_names"]:checked:not(:disabled)')].map(skill =>
      [skill.value, skill.closest('li').querySelector('[data-skill-description]').value.trim()])));
});
