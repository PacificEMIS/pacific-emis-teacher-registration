from django import template

register = template.Library()

@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except Exception:
        return None


@register.filter
def getfield(obj, field_name):
    """Get a model field value by name: {{ item|getfield:'code' }}"""
    try:
        return getattr(obj, field_name, "")
    except Exception:
        return ""
