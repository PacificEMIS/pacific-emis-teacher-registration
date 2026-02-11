from django import template

register = template.Library()

@register.filter
def form_field(form, name):
    """
    Return a BoundField from a form by field name, e.g. {{ form|form_field:"first_name" }}.
    Safe to use with dynamic field names in templates.
    """
    try:
        return form[name]
    except Exception:
        return None


@register.filter
def obj_attr(obj, name):
    """
    Return an attribute value from an object by name, e.g. {{ reg|obj_attr:"checklist_applicant_birth_cert" }}.
    """
    try:
        return getattr(obj, name)
    except Exception:
        return None
