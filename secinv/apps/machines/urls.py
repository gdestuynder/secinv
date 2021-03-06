from django.conf.urls.defaults import patterns, url, include
from . import views


# Regex fragments for easy reading.
machine_slug = r'(?P<machine_slug>[-\w]+)'
section_slug = r'(?P<section_slug>[-\w]+)'
version_number = r'(?P<version_number>[0-9]+)'
compare_with = r'(?P<compare_with>current|previous)'
ac_id = r'(?P<ac_id>[0-9]+)'
item_id = r'(?P<item_id>[0-9]+)'
directive_slug = r'(?P<directive_slug>[-\w]+)'

urlpatterns = patterns('apps.machines.views',
    url(r'^$', 'index', name='machines-index'),

    url(r'^search/', 'search', name='machines-search'),

    url(r'^filters/$', 'machine_filter', name='machine-filter'),

    url(r'^filters/apacheconfig.json$', 'ac_filter_directives_keys',
        name='ac-filter-directives-keys'),
    url(r'^filters/apacheconfig/directive.json$', 'ac_filter_directives',
        name='ac-filter-directives'),

    url(r'^filters/%s/results/$' % section_slug, 'conf_filter_results',
        name='conf-filter-results'),
    url(r'^filters/%s.json$' % section_slug, 'conf_filter_parameters_keys',
        name='conf-filter-parameters-keys'),
    url(r'^filters/%s/directive.json$' % section_slug,
        'conf_filter_parameters', name='conf-filter-parameters'),

    url(r'^datatables/%s.json$' % section_slug, 'datatables',
        name='datatables'),

    url(r'^%s/$' % machine_slug, 'detail', name='machines-detail'),

    url(r'^%s/apacheconfig/%s/$' % (machine_slug, ac_id), 'apacheconfig',
        name='apacheconfig'),

    url(r'^%s/diff/%s/r/%s/%s/$' % (
        machine_slug, section_slug, version_number, compare_with),
        'diff', name='diff'),
    url(r'^%s/diff/%s/%s/r/%s/%s/$' % (
        machine_slug, section_slug, item_id, version_number, compare_with),
        'diff', name='diff-ac'),
)
