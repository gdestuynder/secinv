from django.db.models import get_model
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.encoding import force_unicode, iri_to_uri
from django.utils.safestring import mark_safe, SafeData

from .. import utils
from ..models import ApacheConfig

import re

register = template.Library()

@register.filter
@stringfilter
def split_as_list(value, splitter='|', autoescape=None):
    if not isinstance(value, SafeData):
        value = mark_safe(value)
    value = value.split(splitter)
    #iresult = ""
    #for v in value:
    #    result += '<option value="%s">%s</option>\n' % (v, v)
    return value
split_as_list.is_safe = True
split_as_list.needs_autoescape = True


@register.filter
def dict_get(value, arg):
    """
    Custom template tag used like so:
    {{ dictionary|dict_get:var }}
    """
    return value[arg]
register.filter('dict_get', dict_get)


class DifferNode(template.Node):
    def __init__(self, nodelist, diff_dict, field_name):
        self.nodelist = nodelist
        self.diff_dict = diff_dict
        self.field_name = field_name

    def render(self, context):
        # Remove quotation marks from string value.
        field_name = self.field_name
        if field_name[0] in ('"', "'") and field_name[0] == field_name[-1]:
            field_name = field_name[1:-1]
        else:
            try:
                field_name = template.Variable(field_name).resolve(context)
            except template.VariableDoesNotExist:
                field_name = ''

        try:
            diff_dict = template.Variable(self.diff_dict).resolve(context)
        except template.VariableDoesNotExist:
            diff_dict = {}

        emphasis_tag = ''

        if 'added' in diff_dict and field_name in diff_dict['added']:
            emphasis_tag = 'ins'

        if 'changed' in diff_dict and field_name in diff_dict['changed']:
            emphasis_tag = 'mark'

        if 'removed' in diff_dict and field_name in diff_dict['removed']:
            emphasis_tag = 'del'

        output = self.nodelist.render(context)

        emphasis_start = ('<%s>' % emphasis_tag) if len(emphasis_tag) else ''
        emphasis_end = ('</%s>' % emphasis_tag) if len(emphasis_tag) else ''

        return '%s%s%s' % (emphasis_start, output, emphasis_end)


@register.tag
def differ(parser, token):
    """
    This wraps the enclosed text with the appropriate element: ins, mark, del.

    Requires two arguments: (1) a dictionary of the field differences,
    and (2) a string of the field name.

    Example::

        {% differ system.diff 'rh_rel' %}{{ system.fields.rh_rel }}{% enddiffer %}
    """

    bits = token.split_contents()

    if len(bits) != 3:
        raise template.TemplateSyntaxError('%r tag requires two arguments.' % bits[0])

    diff_dict = bits[1]
    field_name = bits[2]

    nodelist = parser.parse(('enddiffer',))
    parser.delete_first_token()
    return DifferNode(nodelist, diff_dict, field_name)


class SplitAsListNode(template.Node):
    def __init__(self, source_list, destination_list, delimiter=','):
        self.source_list = source_list
        self.destination_list = destination_list
        self.delimiter = delimiter

    def render(self, context):
        source_list = template.Variable(self.source_list).resolve(context)
        new_list = source_list.split(self.delimiter)
        context[self.destination_list] = new_list
        return ''


@register.tag
def split_as_list(parser, token):
    """
    This wraps the enclosed text with the appropriate element: ins, mark, del.

    Requires two arguments: (1) a string delimited by some character,
    and (2) a string of the destination list name.

    Optional first argument: (1) delimiter.

    Example::

        {% split_as_list services.processes as processes_list %}

        or

        {% split_as_list '|' services.processes as processes_list %}
    """

    bits = token.split_contents()
    num_bits = len(bits)

    if num_bits != 4 and num_bits != 5:
        raise template.TemplateSyntaxError(
            '%r tag requires at least four arguments (at most five).' % bits[0])
    elif (bits[2] != 'as' and num_bits == 4) or (bits[3] != 'as' and num_bits == 5):
        raise template.TemplateSyntaxError(
            "%r tag must contain an 'as' argument." % bits[0])

    source_string = bits[1]
    destination_list = bits[3]

    # Remove quotation marks from string value.
    delimiter = '|'
    if num_bits == 5:
        delimiter = bits[1]
        if delimiter[0] in ('"', "'") and delimiter[0] == delimiter[-1]:
            delimiter = delimiter[1:-1]

        source_string = bits[2]
        destination_list = bits[4]

    return SplitAsListNode(source_string, destination_list, delimiter)


def engine(f):
    def apply(text_a, text_b):
        # Don't need to consider autoescape because difflib does the escaping.
        return mark_safe(f(text_a, text_b))
    return apply

register.filter('diff_html', engine(utils.diff_html))
register.filter('diff_table', engine(utils.diff_table))



class GetNestedItemsNode(template.Node):
    def __init__(self, nodelist, field_name, machine_id):
        self.nodelist = nodelist
        self.field_name = field_name
        self.machine_id = machine_id

    def render(self, context):
        field_name = self.field_name
        machine_id = self.machine_id

        # Remove quotation marks from string values.
        if field_name[0] in ('"', "'") and field_name[0] == field_name[-1]:
            field_name = field_name[1:-1]
        else:
            field_name = template.Variable(field_name).resolve(context)

        if machine_id[0] in ('"', "'") and machine_id[0] == machine_id[-1]:
            machine_id = machine_id[1:-1]
        else:
            machine_id = template.Variable(machine_id).resolve(context)

        content = self.nodelist.render(context)

        lines = content.split('\n')
        output = ''

        for line in lines:
            m = re.compile(r'(\s*)<li>(.+)</li>$').match(line)
            if m:
                ws, value = m.groups()
                closing = '</li>'
            else:
                m = re.compile(r'(\s*)<li>(.+)$').match(line)
                if m:
                    ws, value = m.groups()

                    closing = ''
                else:
                    output += '%s\n' % line
                    continue

            try:
                ac = ApacheConfig.objects.get(machine__id=machine_id,
                                              filename=value)

                domains = '\n'

                if domains:
                    domains = '<ul>\n'
                    for d in ac.domains.keys():
                        domains += '  <li>%s</li>\n' % d
                    domains += '</ul>\n'

                line = '%s<li><h6><a href="%s">%s</a></h6>%s%s' % (
                     ws, ac.get_absolute_url(), value, domains, closing)

            except ApacheConfig.DoesNotExist:
                pass

            output += '%s\n' % line

        return '%s' % output


@register.tag
def get_nested_items(parser, token):
    """
    This recursively parses the Apache Configuration files based on the
    includes.

    Requires two arguments: (1) field name, and (2) a machine id.

    Example::

        {% get_nested_items 'filename' machine.id %}
          {{ ac_includes|unordered_list_dl }}
        {% endget_nested_items %}
    """

    bits = token.split_contents()

    if len(bits) != 3:
        raise template.TemplateSyntaxError(
            "%r tag requires two arguments: (field name) and machine_id." % bits[0])

    field_name = bits[1]
    machine_id = bits[2]

    nodelist = parser.parse(('endget_nested_items',))
    parser.delete_first_token()
    return GetNestedItemsNode(nodelist, field_name, machine_id)


@register.filter
def highlight(value, arg=None, autoescape=None):
    """
    Filter syntax-highlights code.
    Optional argument: lexer.
    """
    if autoescape:
        from django.utils.html import conditional_escape
        escaper = conditional_escape
    else:
        escaper = lambda x: x

    from pygments import highlight
    from pygments.lexers import PythonLexer
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name, guess_lexer

    try:
        lexer = get_lexer_by_name(arg, stripnl=False, encoding=u'UTF-8')
    except ValueError:
        try:
            # Guess a lexer by the contents of the block.
            lexer = guess_lexer(value)
        except ValueError:
            # Just make it plain text.
            lexer = get_lexer_by_name(u'text', stripnl=False,
                                      encoding=u'UTF-8')

    # TODO: Translation. uggettext?
    code = highlight(value, lexer, HtmlFormatter())

    return mark_safe(code)
highlight.is_safe = True
