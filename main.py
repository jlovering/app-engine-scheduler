import jinja2
import webapp2
import datetime

from googleapiclient import discovery
from oauth2client.client import GoogleCredentials

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader('templates'))

compute = discovery.build('compute','v1',
    credentials=GoogleCredentials.get_application_default())

projectID = 'wrf-blipmaps'
zoneOpsCached = False
daysToScanBack = 1
instances = {
    'bayarea_4k_p_instances' : {
        'rasp-blipmap-bayarea-4k-p-0' : {
            'name':'rasp-blipmap-bayarea-4k-p-0',
            'zone':'us-west1-a'
        },
        'rasp-blipmap-bayarea-4k-p-1' : {
            'name':'rasp-blipmap-bayarea-4k-p-1',
            'zone':'us-west1-a'
        },
        'rasp-blipmap-bayarea-4k-p-2' : {
            'name':'rasp-blipmap-bayarea-4k-p-2',
            'zone':'us-west1-a'
        }
    }
}


def convert_gcloud_time(gcloudtime):
    # Because why used a fucking standard format?
    # Example: 2018-05-21T13:32:51.357-07:00
    # Note that the TZ offset is HH:MM rather than HHMM
    tzdelta = datetime.timedelta(hours=int(gcloudtime[-6:-3]),minutes=int(gcloudtime[-2:]))
    time = datetime.datetime.strptime(gcloudtime[0:-6], "%Y-%m-%dT%H:%M:%S.%f") - tzdelta
    return time

def get_time_string():
    return datetime.datetime.utcnow().strftime('[%Y-%m-%d %H:%M:%S] ')

def _cache_zone_ops():
    global zoneOpsCached
    ops_of_interest = ['start', 'compute.instances.guestTerminate', 'compute.instances.preempted']
    zones = []
    for g in instances:
        for i in instances[g]:
            instances[g][i]['id'] = compute.instances().get(project=projectID, zone=instances[g][i]['zone'], instance=instances[g][i]['name']).execute()['id']
            if instances[g][i]['zone'] not in zones:
                zones.append(instances[g][i]['zone'])

    ops = []
    for z in zones:
        ops += compute.zoneOperations().list(project='wrf-blipmaps', zone='us-west1-a').execute()['items']

    # filter for just the last day and ops we care about
    ops_today = filter(lambda t: convert_gcloud_time(t['endTime']) > datetime.datetime.utcnow() - datetime.timedelta(days=daysToScanBack) and t['operationType'] in ops_of_interest, ops)

    # sort by completions time
    ops_today_r_sorted = sorted(ops_today, key=lambda t: convert_gcloud_time(t['endTime']), reverse=True)

    for g in instances:
        for i in instances[g]:
            instances[g][i]['lastStart'] = []
            instances[g][i]['lastComplete'] = []
            instances[g][i]['lastPreempt'] = []
            instances[g][i]['ops'] = filter(lambda t: t['targetId'] == instances[g][i]['id'], ops_today_r_sorted)
            for o in instances[g][i]['ops']:
                if o['operationType'] == 'start':
                    instances[g][i]['lastStart'].append(convert_gcloud_time(o['endTime']))
                if o['operationType'] == 'compute.instances.guestTerminate':
                    instances[g][i]['lastComplete'].append(convert_gcloud_time(o['endTime']))
                if o['operationType'] == 'compute.instances.preempted':
                    instances[g][i]['lastPreempt'].append(convert_gcloud_time(o['endTime']))

    zoneOpsCached = True

def _get_last_time(group, instance, prop):
    if not zoneOpsCached:
        _cache_zone_ops()

    if len(instances[group][instance][prop]) > 0:
        return instances[group][instance][prop][0]
    else:
        return None

def get_last_completed_time(group, instance):
    return _get_last_time(group, instance, 'lastComplete')

def get_last_started_time(group, instance):
    return _get_last_time(group, instance, 'lastStart')

def get_last_preempt_time(group, instance):
    return _get_last_time(group, instance, 'lastPreempt')

def get_last_run_elapsed(group, instance):
    start = get_last_started_time(group, instance)
    stop = get_last_completed_time(group, instance)

    if start and stop:
        delta = stop - start
    else:
        return None

    if delta.total_seconds() < 0:
        return None
    else:
        return delta.total_seconds()

def get_last_run_preempted(group, instance):
    start = get_last_started_time(group, instance)
    preempt = get_last_preempt_time(group, instance)

    if start and preempt:
        return start < preempt
    else:
        return False

def get_preemption_count(group, instance):
    return len(instances[group][instance]['lastPreempt'])

def start_instance(zone, instance):
    """starts instance"""
    request = compute.instances().start(
        project=projectID,
        zone=zone,
        instance=instance)
    response = request.execute()
    return response

def get_status(zone, instance):
    request = compute.instances().get(
        project=projectID,
        zone=zone,
        instance=instance)
    response = request.execute()
    return response['status']


def InstanceGroupStarter(group):
    response = ""
    for instance in instances[group]:
        start_instance(instances[group][instance]['zone'], instances[group][instance]['name'])
        response += get_time_string() + "Starting instance: " + instances[group][instance]['name'] + "\r\n"
    return response

def MonitorGroup(group):
    response = ""
    for i in instances[group]:
        if get_last_run_preempted(group, instances[group][i]['name']):
            start_instance(instances[group][i]['zone'], instances[group][i]['name'])
            response += get_time_string() + "Instance: " + instances[group][i]['name'] + " was preempted, restarting" + "\r\n"
    if len(response) == 0:
        return get_time_string() + "All instances running normally"
    return response

class BayArea4kStartTrigger(webapp2.RequestHandler):
    def get(self):
        self.response.write(InstanceGroupStarter('bayarea_4k_p_instances'))

class BayArea4kMonitorTrigger(webapp2.RequestHandler):
    def get(self):
        self.response.write(MonitorGroup('bayarea_4k_p_instances'))

class StatusPage(webapp2.RequestHandler):
    def get(self):
        status_items = [];
        for group in instances:
            for instance in instances[group]:
                    status_items.append({
                        'instance_name': instance,
                        'instance_status': get_status(instances[group][instance]['zone'], instances[group][instance]['name']),
                        'instance_started': str(get_last_started_time(group, instance)),
                        'instance_completed': str(get_last_completed_time(group, instance)),
                        'instance_elapsed': str(get_last_run_elapsed(group, instance)),
                        'instance_was_preempted': str(get_last_run_preempted(group, instance)),
                        'instance_preempted_count': str(get_preemption_count(group, instance))
                        })

        data = {}
        data['title'] = "Instance Status"
        data['date'] = datetime.datetime.utcnow()
        data['status_items'] = status_items

        template = jinja_environment.get_template('status.html')
        self.response.out.write(template.render(data))

for g in instances:
    for i in instances[g]:
        assert instances[g][i]['name'] == i, "Missmatched key and name \"%s\" != \"%s\"" % (i, instances[g][i]['name'])

app = webapp2.WSGIApplication([
    ('/BayArea4kStart', BayArea4kStartTrigger),
    ('/BayArea4kMonitor', BayArea4kMonitorTrigger),
    ('/Status', StatusPage),
], debug=True)

