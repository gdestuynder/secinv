from django.db.models import Q
from django.core import serializers
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseNotFound, Http404
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.utils import simplejson

from .models import Machine, Services, System, RPMs, Interface, SSHConfig, \
                    IPTables, ApacheConfig, PHPConfig, MySQLConfig
from .forms import MachineSearchForm
from .utils import diff_list, diff_dict, get_version_diff, get_version_diff_field

from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
from pygments.lexers import ApacheConfLexer

from reversion.models import Version

import re
import json

DIFF_SECTION_SLUGS = ('iptables', 'httpd-conf', 'php-config', 'mysql-config')
CONFIG_SECTIONS = ('apacheconfig', 'phpconfig', 'mysqlconfig')

def get_all_domains():
    all_domains = []

    m_all = Machine.objects.all()
    for m in m_all:
        a_m = ApacheConfig.objects.filter(machine__id=m.id, active=True).all()
        for a in a_m:
            for fn in a.included:
                try:
                    i_a = ApacheConfig.objects.get(machine__id=m.id,
                                                   filename=fn,
                                                   active=True)
                    for k in i_a.domains.keys():
                        if not [m.hostname, k, i_a.id] in all_domains:
                            all_domains.append([m.hostname, k, i_a.id])
                except ApacheConfig.DoesNotExist:
                    pass

    all_domains.sort()
    return all_domains

def get_all_machines(order_by='id'):
    return Machine.objects.all().order_by(order_by)

#
# TODO: Apache Parser -- Force directives to be uppercased.
#
def get_all_directives():
    all_directives_dict = {}

    a_all = ApacheConfig.objects.filter(active=True).all()
    for a in a_all:
        for k, v in a.directives.iteritems():
            if k in all_directives_dict:
                all_directives_dict[k] += v
            else:
                all_directives_dict[k] = v

    all_directives = []

    for key, values in all_directives_dict.iteritems():
        all_directives.append([key, list(set(values))])

    all_directives.sort()
    return all_directives


def get_all_items(section_slug):
    if not section_slug in CONFIG_SECTIONS:
        raise ValueError
        #return []

    all_items_dict = {}

    if section_slug == 'phpconfig':
        a_all = PHPConfig.objects.filter(active=True).all()
    elif section_slug == 'mysqlconfig':
        a_all = MySQLConfig.objects.filter(active=True).all()

    for a in a_all:
        for k, v in a.items.iteritems():
            if k in all_items_dict:
                all_items_dict[k] += v
            else:
                all_items_dict[k] = v

    all_items = []

    for key, values in all_items_dict.iteritems():
        all_items.append([key, list(set(values))])

    all_items.sort()
    return all_items


def index(request):
    """Machines index page."""
    machines = Machine.objects.all()
    query = request.GET.get('q', '')

    template_context = {'machines': machines,
                        'query': query,
                        'all_machines_hn': get_all_machines('-hostname'),
                        'all_machines_ip': get_all_machines('-sys_ip'),
                        'all_domains': get_all_domains(),
                        'all_directives': get_all_directives(),
                        'all_php_items': get_all_items('phpconfig'),
                        'all_mysql_items': get_all_items('mysqlconfig'),}
    return render_to_response('machines/index.html', template_context,
                              context_instance=RequestContext(request))


# View that that returns the JSON result.
def history(request, machine_slug):
    # TODO: prevent calls
    #if not request.is_ajax():
    #    return HttpResponse(status=400)

    m = get_object_or_404(Machine, hostname=machine_slug)

    # Retrieve all the system history.
    system_history = System.objects.filter(machine__id=m.id).order_by(
        '-date_added').all()

    # Serialize the result of the database retrieval to JSON and send an
    # application/json response.
    return HttpResponse(serializers.serialize('json', system_history),
                        mimetype='application/json')


def recurse_ac_includes(ac, field_name='filename'):
    ac_includes = []
    for fn in ac.included:
        try:
            i_ac = ApacheConfig.objects.get(machine__id=ac.machine_id, filename=fn,
                                            active=True)

            l = i_ac.__getattribute__(field_name)

            if i_ac.included:
                l = [i_ac.__getattribute__(field_name), recurse_ac_includes(i_ac)]

            ac_includes.append(l)

        except ApacheConfig.DoesNotExist:
            pass

    return ac_includes


def detail(request, machine_slug):
    m = get_object_or_404(Machine, hostname=machine_slug)
    query = request.GET.get('q', '')

    ## System.
    system_latest = []
    system_versions = []
    system_history = System.objects.filter(machine__id=m.id).order_by(
        '-date_added').all()


    if system_history.exists():
        system_latest = system_history[0]

        # Get historical versions of System objects.
        system_versions = get_version_diff(system_history[0])

    ## Services.
    services_latest = []
    services_versions = []
    services_history = Services.objects.filter(machine__id=m.id).order_by(
        '-date_added').all()

    if services_history.exists():
        services_latest = services_history[0]

        # Get historical versions of Services objects.
        services_versions = get_version_diff(services_history[0], ',')
    


    ## Interfaces.

    # Get latest interfaces (select by distinct interface name).
    distinct_interfaces = Interface.objects.filter(
        machine__id=m.id).values_list('i_name', flat=True).distinct()

    interfaces_latest = []
    interfaces_versions = []
    for i in distinct_interfaces:
        i_latest = Interface.objects.filter(machine__id=m.id,
                                            i_name=i).latest()
        interfaces_latest.append(i_latest)

        # Append each unique interface's history.
        i_v = get_version_diff(i_latest)
        interfaces_versions += i_v

    if interfaces_versions:
        interfaces_versions = sorted(interfaces_versions,
                                     key=lambda k: k['timestamp'],
                                     reverse=True)


    ## SSHConfig.
    sshconfig_latest = []
    sshconfig_versions = []
    sshconfig_history = SSHConfig.objects.filter(machine__id=m.id).order_by(
        '-date_added').all()

    if sshconfig_history.exists():
        sshconfig_latest = sshconfig_history[0]

        sshconfig_versions = get_version_diff(sshconfig_history[0], '\n')


    # RPMs.
    rpms_list = []
    rpms_date_added = None
    rpms_versions = []
    rpms_history = RPMs.objects.filter(machine__id=m.id).order_by(
        '-date_added').all()

    if rpms_history.exists():
        rpms_list = re.split('\n', rpms_history[0].v_rpms)
        rpms_date_added = rpms_history[0].date_added

        rpms_versions = get_version_diff(rpms_history[0], '\n')
    

    rpms_latest = {'installed': rpms_list, 'date_added': rpms_date_added}


    ## iptables.
    iptables_latest = []
    iptables_versions = []
    iptables_history = IPTables.objects.filter(machine__id=m.id).order_by(
        '-date_added').all()

    if iptables_history.exists():
        iptables_latest = iptables_history[0]

        iptables_versions = get_version_diff_field(iptables_history[0], 'body')


    ## Apache configuration files.
    apacheconfig_latest = []
    apacheconfig_includes = []
    ac_includes = []
    apacheconfig_history = ApacheConfig.objects.filter(machine__id=m.id,
        active=True).order_by('-date_added').all()


    # Get historical versions of ApacheConfig objects.
    apacheconfig_versions = []
    for a_h in apacheconfig_history:
        a_v = get_version_diff_field(a_h, 'body')
        apacheconfig_versions += a_v

    if apacheconfig_versions:
        apacheconfig_versions = sorted(apacheconfig_versions,
                                       key=lambda k: k['timestamp'],
                                       reverse=True)

    apacheconfig_latest_body = ''
    if apacheconfig_history.exists():
        try:
            apacheconfig_latest = ApacheConfig.objects.filter(machine__id=m.id,
                filename__endswith='/httpd.conf', active=True).order_by(
                '-date_added').all()[0]
        except:
            pass

        try:
            apacheconfig_latest_body = highlight(apacheconfig_latest.body,
                                                 ApacheConfLexer(),
                                                 HtmlFormatter())

            body = ''
            lines = re.split('\n', apacheconfig_latest_body)
            for line in lines:
                ls = re.split(' ', line.replace('<span class="nb">', '').replace('</span>', ''))
                if len(ls) == 2 and ls[0].lower() == 'include':
                    # TODO: in Apache Config Parser, handle ``quoted`` Include filenames.
    
                    try:
                        a = ApacheConfig.objects.get(machine__id=m.id,
                                                     filename__endswith=ls[1],
                                                     active=True)
                        i_fn = '<a href="%s">%s</a>' % (a.get_absolute_url(), ls[1])
                    except (ApacheConfig.DoesNotExist,
                            ApacheConfig.MultipleObjectsReturned):
                        i_fn = '%s' % ls[1]
    
                    line = '<span class="nb">%s</span> %s' % (ls[0], i_fn)
                body += '%s\n' % line
            apacheconfig_latest_body = body
        except TypeError:
            apacheconfig_latest_body = apacheconfig_latest.body


        for fn in apacheconfig_latest.included:
            try:
                i_ac = ApacheConfig.objects.get(machine__id=m.id, filename=fn,
                                                active=True)

                apacheconfig_includes.append(i_ac)
            except ApacheConfig.DoesNotExist:
                pass

        # Recurse includes.
        ac_includes = recurse_ac_includes(apacheconfig_latest)


    ## PHP configuration file.
    phpconfig_latest = []
    phpconfig_versions = []
    phpconfig_history = PHPConfig.objects.filter(machine__id=m.id, active=True
        ).order_by('-date_added').all()

    if phpconfig_history.exists():
        phpconfig_latest = phpconfig_history[0]

        phpconfig_versions = get_version_diff_field(phpconfig_history[0], 'body')


    ## MySQL configuration file.
    mysqlconfig_latest = []
    mysqlconfig_versions = []
    mysqlconfig_history = MySQLConfig.objects.filter(machine__id=m.id, active=True
        ).order_by('-date_added').all()

    if mysqlconfig_history.exists():
        mysqlconfig_latest = mysqlconfig_history[0]

        mysqlconfig_versions = get_version_diff_field(mysqlconfig_history[0], 'body')


    template_context = {'query': query,
                        'machine': m,
                        'system': system_latest,
                        'system_versions': system_versions,
                        'services': services_latest,
                        'services_versions': services_versions,
                        'rpms': rpms_latest,
                        'rpms_versions': rpms_versions,
                        'interfaces': interfaces_latest,
                        'interfacess_versions': interfaces_versions,
                        'sshconfig': sshconfig_latest,
                        'sshconfig_versions': sshconfig_versions,
                        'iptables': iptables_latest,
                        'iptables_versions': iptables_versions,
                        'apacheconfig': apacheconfig_latest,
                        'apacheconfig_versions': apacheconfig_versions,
                        'apacheconfig_latest_body': apacheconfig_latest_body,
                        'apacheconfig_includes': apacheconfig_includes,
                        'ac_includes': ac_includes,
                        'phpconfig': phpconfig_latest,
                        'phpconfig_versions': phpconfig_versions,
                        'mysqlconfig': mysqlconfig_latest,
                        'mysqlconfig_versions': mysqlconfig_versions,
                        'all_machines_hn': get_all_machines('-hostname'),
                        'all_machines_ip': get_all_machines('-sys_ip'),
                        'all_domains': get_all_domains(),
                        'all_directives': get_all_directives(),
                        'all_php_items': get_all_items('phpconfig'),
                        'all_mysql_items': get_all_items('mysqlconfig'),}
    return render_to_response('machines/detail.html', template_context,
                              context_instance=RequestContext(request))


def search(request):
    query = request.GET.get('q', '')
    terms = query.split()
    results = []
    excerpts = {}

    if query:
        form = MachineSearchForm(request.GET)
        if form.is_valid():
            results = form.get_result_queryset()
    else:
        form = MachineSearchForm()

    template_context = {'form': form,
                        'results': results,
                        'query': query,
                        'terms': terms,
                        'all_machines_hn': get_all_machines('-hostname'),
                        'all_machines_ip': get_all_machines('-sys_ip'),
                        'all_domains': get_all_domains(),
                        'all_directives': get_all_directives()}
    return render_to_response('machines/search.html', template_context,
        context_instance=RequestContext(request))


def httpd_conf(request, machine_slug, ac_id):
    m = get_object_or_404(Machine, hostname=machine_slug)
    ac = get_object_or_404(ApacheConfig, id=ac_id)

    highlighted_code = highlight(ac.body, ApacheConfLexer(), HtmlFormatter())

    # TODO: ADD AS FILTER.
    body = ''
    lines = re.split('\n', highlighted_code)
    for line in lines:
        ls = re.split(' ', line.replace('<span class="nb">', '').replace('</span>', ''))
        if len(ls) == 2 and ls[0].lower() == 'include':
            # TODO: in Apache Config Parser, handle ``quoted`` Include filenames.

            try:
                a = ApacheConfig.objects.get(machine__id=m.id,
                                             filename__endswith=ls[1],
                                             active=True)
                i_fn = '<a href="%s">%s</a>' % (a.get_absolute_url(), ls[1])
            except (ApacheConfig.DoesNotExist, ApacheConfig.MultipleObjectsReturned):
                i_fn = '%s' % ls[1]

            line = '<span class="nb">%s</span> %s' % (ls[0], i_fn)
        body += '%s\n' % line

    # Get historical versions of ApacheConfig object.
    apacheconfig_versions = get_version_diff_field(ac, 'body')

    # Get includes.
    apacheconfig_includes = []
    for fn in ac.included:
        try:
            i_ac = ApacheConfig.objects.get(machine__id=m.id, filename=fn,
                                            active=True)

            apacheconfig_includes.append(i_ac)
        except ApacheConfig.DoesNotExist:
            pass

    # Recurse includes.
    ac_includes = recurse_ac_includes(ac)

    query = request.GET.get('q', '')
    template_context = {'machine': m,
                        'query': query,
                        'ac': ac,
                        'ac_body': body,
                        'all_machines_hn': get_all_machines('-hostname'),
                        'all_machines_ip': get_all_machines('-sys_ip'),
                        'all_domains': get_all_domains(),
                        'all_directives': get_all_directives(),
                        'apacheconfig_versions': apacheconfig_versions,
                        'apacheconfig_includes': apacheconfig_includes,
                        'ac_includes': ac_includes}
    return render_to_response('machines/httpd_conf.html', template_context,
        context_instance=RequestContext(request))


def diff(request, machine_slug, section_slug, version_number,
         compare_with='previous', item_id=None):
    if section_slug not in DIFF_SECTION_SLUGS:
        raise Http404

    m = get_object_or_404(Machine, hostname=machine_slug)
    query = request.GET.get('q', '')
    v_num = int(version_number)

    body_current = ''
    body_previous = ''

    if section_slug == 'iptables':
        past_history = IPTables.objects.filter(machine__id=m.id).order_by(
            '-date_added').all()
    elif section_slug == 'httpd-conf':
        past_history = ApacheConfig.objects.filter(machine__id=m.id,
            id=item_id, active=True).order_by('-date_added').all()
    elif section_slug == 'php-config':
        past_history = PHPConfig.objects.filter(machine__id=m.id,
            active=True).order_by('-date_added').all()
    elif section_slug == 'mysql-config':
        past_history = MySQLConfig.objects.filter(machine__id=m.id,
            active=True).order_by('-date_added').all()


    if past_history.exists():
        if compare_with == 'current':
            body_current = past_history[0].body

        obj_versions = Version.objects.get_for_object(
            past_history[0]).order_by('revision')
        if obj_versions:
            try:
                if compare_with == 'current':
                    body_previous = obj_versions[v_num - 1].field_dict['body']
                elif compare_with == 'previous':
                    body_current = obj_versions[v_num - 1].field_dict['body']
                    body_previous = obj_versions[v_num - 2].field_dict['body']
            except (IndexError, AssertionError):
                pass

            older_version = ''
            newer_version = ''

            if compare_with == 'current':
                if (v_num - 2) < len(obj_versions):
                    older_version = v_num - 1 # index + 1
                if v_num < len(obj_versions):
                    newer_version = v_num + 1
            elif compare_with == 'previous':
                if (v_num - 3) < len(obj_versions):
                    older_version = v_num - 2
                if v_num < len(obj_versions):
                    newer_version = v_num + 1

            if older_version < 0:
                older_version = ''
            if newer_version < 0:
                newer_version = ''
    else:
        raise Http404

    v_num_previous = 0
    if v_num > 0:
        v_num_previous = v_num - 1

    template_context = {'machine': m,
                        'query': query,
                        'section': section_slug,
                        'obj_current': past_history[0],
                        'body_current': body_current,
                        'body_previous': body_previous,
                        'version_current': str(v_num),
                        'version_previous': str(v_num_previous),
                        'older_version': str(older_version),
                        'newer_version': str(newer_version),
                        'compare_with': compare_with,
                        'all_machines_hn': get_all_machines('-hostname'),
                        'all_machines_ip': get_all_machines('-sys_ip'),
                        'all_domains': get_all_domains(),
                        'all_directives': get_all_directives()}
    return render_to_response('machines/diff.html', template_context,
                              context_instance=RequestContext(request))


def ac_filter_directives_keys(request):
    #if not request.is_ajax():
    #    return HttpResponse(status=400)

    all_directives = get_all_directives()
    result = [f[0] for f in all_directives]

    # Serialize the result of the database retrieval to JSON and send an
    # application/json response.
    return HttpResponse(simplejson.dumps(result), mimetype='application/json')

def ac_filter_directives(request):
    #if not request.is_ajax() or request.method != 'POST':
    #    return HttpResponse(status=400)

    result = ''
    if request.method == 'POST':
        directive = request.POST.get('parameter', '')

        if directive:
            all_directives = get_all_directives()
            for v in all_directives:
                if v[0] == directive:
                    result = v[1]
                    break

    return HttpResponse(simplejson.dumps(result), mimetype='application/json')


def conf_filter_parameters_keys(request, section_slug):
    #if not request.is_ajax() or not section_slug in CONFIG_SECTIONS:
    #    return HttpResponse(status=400)

    if section_slug == 'apacheconfig':
        all_params = get_all_directives()
    elif section_slug in ('phpconfig', 'mysqlconfig'):
        all_params = get_all_items(section_slug)

    result = [f[0] for f in all_params]

    # Serialize the result of the database retrieval to JSON and send an
    # application/json response.
    return HttpResponse(simplejson.dumps(result), mimetype='application/json')

def conf_filter_parameters(request, section_slug):
    #if not request.is_ajax() or request.method != 'POST' or \
    #   not section_slug in CONFIG_SECTIONS:
    #    return HttpResponse(status=400)

    result = ''
    if request.method == 'POST':
        parameter = request.POST.get('parameter', '')

        if parameter:
            if section_slug == 'apacheconfig':
                all_params = get_all_directives()
            elif section_slug in ('phpconfig', 'mysqlconfig'):
                all_params = get_all_items(section_slug)

            for v in all_params:
                if v[0] == parameter:
                    result = v[1]
                    break

    return HttpResponse(simplejson.dumps(result), mimetype='application/json')


def machine_filter(request):
    """Find machine by hostname, IP, or domain and redirect."""
    if request.method != 'GET':
        return HttpResponse(status=400)

    hostname = request.GET.get('machine_hostname', '')
    ip = request.GET.get('machine_ip', '')
    domain = request.GET.get('machine_domain', '')

    m_hn = ''
    if hostname:
        m_hn = hostname
    elif ip:
        m_hn = ip
    elif domain:
        m_hn = domain

    if m_hn:
        m = get_object_or_404(Machine, hostname=m_hn)
        destination = reverse('machines-detail', args=[m.hostname])
    else:
        destination = reverse('machines-index')

    return HttpResponseRedirect(destination)

'''
def ac_filter_results(request):
    """Filter ApacheConfig objects by parameters and values."""
    if request.method != 'GET':
        return HttpResponse(status=400)

    query = request.GET.get('q', '')
    ac_parameter = request.GET.get('ac_parameter', '')
    ac_value = request.GET.get('ac_value', '')

    results = []

    # Store matching ApacheConfig objects in results list.
    a_all = ApacheConfig.objects.filter(active=True).all()
    for a in a_all:
        for param, values in a.directives.iteritems():
            if param == ac_parameter or ac_parameter == '':
                for v in values:
                    if v == ac_value or ac_value == '':
                        results.append([param, v, a])

    results.sort()

    template_context = {'query': query,
                        'ac_parameter': ac_parameter,
                        'ac_value': ac_value,
                        'results': results,
                        'all_machines_hn': get_all_machines('-hostname'),
                        'all_machines_ip': get_all_machines('-sys_ip'),
                        'all_domains': get_all_domains(),
                        'all_directives': get_all_directives()}
    return render_to_response('machines/httpd_results.html', template_context,
                              context_instance=RequestContext(request))
'''


def conf_filter_results(request, section_slug):
    """Filter other configuration objects by parameters and values."""
    if request.method != 'GET' or not section_slug in CONFIG_SECTIONS:
        return HttpResponse(status=400)

    query = request.GET.get('q', '')
    conf_parameter = request.GET.get('conf_parameter', '')
    conf_value = request.GET.get('conf_value', '')

    results = []

    # Store matching objects in results list.

    parameters_fn = 'items'
    if section_slug == 'apacheconfig':
        a_all = ApacheConfig.objects.filter(active=True).all()
        parameters_fn = 'directives'
    elif section_slug == 'phpconfig':
        a_all = PHPConfig.objects.filter(active=True).all()
    elif section_slug == 'mysqlconfig':
        a_all = MySQLConfig.objects.filter(active=True).all()

    for a in a_all:
        for param, values in a.__getattribute__(parameters_fn).iteritems():
            if param == conf_parameter or conf_parameter == '':
                for v in values:
                    if conf_value == v or conf_value == '':
                        results.append([param, v, a])

    results.sort()


    template_context = {'query': query,
                        'conf_parameter': conf_parameter,
                        'conf_value': conf_value,
                        'results': results,
                        'section_slug': section_slug,
                        'all_machines_hn': get_all_machines('-hostname'),
                        'all_machines_ip': get_all_machines('-sys_ip'),
                        'all_domains': get_all_domains(),
                        'all_directives': get_all_directives(),
                        'all_php_items': get_all_items('phpconfig'),
                        'all_mysql_items': get_all_items('mysqlconfig'),}
    return render_to_response('machines/conf_results.html', template_context,
                              context_instance=RequestContext(request))

