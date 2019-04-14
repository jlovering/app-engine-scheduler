import jinja2
import webapp2
import datetime
import os

from googleapiclient import discovery
from oauth2client.client import GoogleCredentials

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader('templates'))

compute = discovery.build('compute','v1',
    credentials=GoogleCredentials.get_application_default())

projectID = 'wrf-blipmaps'
zoneOpsCached = False
instancesCached = False
daysToScanBack = 1
maxRunningInstancesPerZone = 4
liveDelete = False
machineType = 'n1-highcpu-8'

simulations = {
    'bayarea-4k' : {
        'TZ' : 'America/Los_Angeles',
        'bucket_uri' : 'gs://bucket-blipmap-bayarea-4k',
        'docker_image' : 'gcr.io/wrf-blipmaps/rasp-blipmap-bayarea-4k:latest',
        'site_name' : 'BAYAREA',
        'starthh' : 12,
        'max_expected_run' : 700,
    },
    'sask-4k' : {
        'TZ' : 'America/Regina',
        'bucket_uri' : 'gs://bucket-blipmap-sask-4k',
        'docker_image' : 'gcr.io/wrf-blipmaps/rasp-blipmap-sask-4k:latest',
        'site_name' : 'SASK',
        'starthh' : 9,
        'max_expected_run' : 1600,
    },
}

deploy_zones = [
    'us-west1-a',
    'us-central1-c'
    ]

current_instances = {}

recent_instances = {}

def convert_gcloud_time(gcloudtime):
    # Because why used a fucking standard format?
    # Example: 2018-05-21T13:32:51.357-07:00
    # Note that the TZ offset is HH:MM rather than HHMM
    tzdelta = datetime.timedelta(hours=int(gcloudtime[-6:-3]),minutes=int(gcloudtime[-2:]))
    time = datetime.datetime.strptime(gcloudtime[0:-6], "%Y-%m-%dT%H:%M:%S.%f") - tzdelta
    return time

def get_time_string():
    return datetime.datetime.utcnow().strftime('[%Y-%m-%d %H:%M:%S] ')

def _cache_current_instances():
    global instancesCached
    for zone in deploy_zones:
        request = compute.instances().list(project=projectID, zone=zone)
        while request is not None:
            response = request.execute()
            for i in response['items']:
                inst = {
                'name' : i['name'],
                'zone' : i['zone'].split('/')[-1],
                'id' : i['id'],
                'status' : i['status']
                }
                for m in i['metadata']['items']:
                    if m['key'] == 'max_expected_run':
                        inst['max_expected_run'] = m['value']
                current_instances[inst['name']] = inst
            request = compute.instances().list_next(previous_request=request, previous_response=response)
    instancesCached = True

def _cache_zone_ops():
    global zoneOpsCached

    ops_of_interest = ['start', 'reset', 'compute.instances.guestTerminate', 'compute.instances.preempted', 'insert', 'delete']
    ops = []
    for z in deploy_zones:
        ops += compute.zoneOperations().list(project=projectID, zone=z).execute()['items']

    # filter for just the last day and ops we care about
    ops_today = filter(lambda t: convert_gcloud_time(t['endTime']) > datetime.datetime.utcnow() - datetime.timedelta(days=daysToScanBack) and t['operationType'] in ops_of_interest, ops)

    # sort by completions time
    ops_today_r_sorted = sorted(ops_today, key=lambda t: convert_gcloud_time(t['endTime']), reverse=True)

    for o in ops_today_r_sorted:
        name = o['targetLink'].split('/')[-1]
        if not name in recent_instances:
            recent_instances[name] = {
                'name' : name,
                'zone' : o['zone'].split('/')[-1],
                'id' : o['targetId'],
                'lastStart' : [],
                'lastStop' : [],
                'lastComplete' : [],
                'lastPreempt' : [],
                'lastCreate' : [],
                'lastDelete' : []
                }
        if o['operationType'] == 'start' or o['operationType'] == 'reset':
            recent_instances[name]['lastStart'].append(convert_gcloud_time(o['endTime']))
        if o['operationType'] == 'stop':
            recent_instances[name]['lastStop'].append(convert_gcloud_time(o['endTime']))
        if o['operationType'] == 'compute.instances.guestTerminate':
            recent_instances[name]['lastComplete'].append(convert_gcloud_time(o['endTime']))
        if o['operationType'] == 'compute.instances.preempted':
            recent_instances[name]['lastPreempt'].append(convert_gcloud_time(o['endTime']))
        if o['operationType'] == 'insert':
            recent_instances[name]['lastCreate'].append(convert_gcloud_time(o['endTime']))
        if o['operationType'] == 'delete':
            recent_instances[name]['lastDelete'].append(convert_gcloud_time(o['endTime']))

    zoneOpsCached = True

def _get_last_time(instance, prop):
    if not zoneOpsCached:
        _cache_zone_ops()

    if len(recent_instances[instance][prop]) > 0:
        return recent_instances[instance][prop][0]
    else:
        return None

def get_last_completed_time(instance):
    return _get_last_time(instance, 'lastComplete')

def get_last_started_time(instance):
    return _get_last_time(instance, 'lastStart')

def get_last_preempt_time(instance):
    return _get_last_time(instance, 'lastPreempt')

def get_current_run_elapsed(instance):
    start = get_last_started_time(instance)
    stop = get_last_completed_time(instance)

    if not start:
        return 0

    # If there were starts and stops, check the run is active
    if start and stop and start < stop:
        return 0

    print datetime.datetime.utcnow(), start
    delta = datetime.datetime.utcnow() - start
    print delta

    if delta.total_seconds() < 0:
        return 0
    else:
        return delta.total_seconds()

def get_last_run_elapsed(instance):
    start = get_last_started_time(instance)
    stop = get_last_completed_time(instance)

    if start and stop:
        delta = stop - start
    else:
        return 0

    if delta.total_seconds() < 0:
        return 0
    else:
        return delta.total_seconds()

def get_last_run_preempted(instance):
    start = get_last_started_time(instance)
    preempt = get_last_preempt_time(instance)

    if start and preempt:
        return start < preempt
    else:
        return False

def get_last_run_completed(instance):
    start = get_last_started_time(instance)
    complete = get_last_completed_time(instance)

    if start and complete:
        return start < complete
    else:
        return False

def get_preemption_count(instance):
    if not zoneOpsCached:
        _cache_zone_ops()
    return len(recent_instances[instance]['lastPreempt'])

def get_still_instantance(instance):
    if not instancesCached:
        _cache_current_instances()
    return instance in current_instances

def start_instance(zone, instance):
    """starts instance"""
    return compute.instances().start(
        project=projectID,
        zone=zone,
        instance=instance).execute()

def restart_instance(zone, instance):
    """restarts instance"""
    return compute.instances().reset(
        project=projectID,
        zone=zone,
        instance=instance).execute()

def stop_instance(zone, instance):
    """stop instance"""
    return compute.instances().stop(
        project=projectID,
        zone=zone,
        instance=instance).execute()

def delete_instance(zone, instance):
    return compute.instances().delete(
        project=projectID,
        zone=zone,
        instance=instance).execute()

def find_zone():
    if not instancesCached:
        _cache_current_instances()

    zones = []
    for z in deploy_zones:
        zones.append({
            'zone' : z,
            'count' : len(filter(lambda t: current_instances[t]['zone'] == z and current_instances[t]['status'] != 'TERMINATED', current_instances))
            })
    print zones
    candidate = min(zones, key=lambda k: k['count'])
    if candidate['count'] >= maxRunningInstancesPerZone:
        return None
    else:
        return candidate['zone']

def create_instance(zone, group, index, name):
    sourceDiskImage = compute.images().get(
        project=projectID,
        image='rasp-blipmap-template').execute()['selfLink']

    startup_script = open(
        os.path.join(
            os.path.dirname(__file__), 'rasp-blipmap-startup.sh'), 'r').read()

    config = {
        'name': name,
        'machineType': "zones/%s/machineTypes/%s" % (zone, machineType),
        'canIpForward': False,
        # Specify a network interface with NAT to access the public
        # internet.
        'networkInterfaces': [{
            'network': 'global/networks/default',
            'accessConfigs': [{
                'type': 'ONE_TO_ONE_NAT',
                'networkTier': "STANDARD",
                'name': 'External NAT',
            }]
        }],
        # Specify the boot disk and the image to use as a source.
        'disks': [{
            'boot': True,
            'autoDelete': True,
            'initializeParams': {
                'sourceImage': sourceDiskImage,
            }
        }],
        # Allow the instance to access cloud storage and logging.
        'serviceAccounts': [{
            'email': 'default',
            'scopes': [
                'https://www.googleapis.com/auth/devstorage.read_only',
                'https://www.googleapis.com/auth/logging.write',
                'https://www.googleapis.com/auth/monitoring.write',
                'https://www.googleapis.com/auth/servicecontrol',
                'https://www.googleapis.com/auth/service.management.readonly',
                'https://www.googleapis.com/auth/trace.append'
            ]
        }],
        # Preemptible image
        'scheduling': {
            'automaticRestart': False,
            'onHostMaintenance': 'TERMINATE',
            'preemptible': True
        },
        # Metadata is readable from the instance and allows you to
        # pass configuration from deployment scripts to instances.
        'metadata': {
            'items': [
                {
                    "key": "TZ",
                    "value": simulations[group]['TZ']
                },
                {
                    "key": "bucket_uri",
                    "value": simulations[group]['bucket_uri']
                },
                {
                    "key": "day_offset",
                    "value": "%d" % index
                },
                {
                    "key": "docker_image",
                    "value": simulations[group]['docker_image']
                },
                {
                    "key": "site_name",
                    "value": simulations[group]['site_name']
                },
                {
                    "key": "starthh",
                    "value": simulations[group]['starthh']
                },
                {
                    "key": "max_expected_run",
                    "value": simulations[group]['max_expected_run']
                },
                {
                    "key": "startup-script",
                    "value": startup_script
                }
            ],
        }
    }
    return compute.instances().insert(
        project=projectID,
        zone=zone,
        body=config).execute()

def get_status(instance):
    zone = recent_instances[instance]['zone']
    return compute.instances().get(
        project=projectID,
        zone=zone,
        instance=instance).execute()['status']

def MonitorTrigger():
    if not instancesCached:
        _cache_current_instances()
    response = ""
    for i in current_instances:
        if get_last_run_preempted(current_instances[i]['name']):
            start_instance(current_instances[i]['zone'], current_instances[i]['name'])
            response += get_time_string() + "Instance: " + current_instances[i]['name'] + " was preempted, restarting" + "\r\n"
            continue
        if get_current_run_elapsed(current_instances[i]['name']) > current_instances[i]['max_expected_run']:
            restart_instance(current_instances[i]['zone'], current_instances[i]['name'])
            response += get_time_string() + "Instance: " + current_instances[i]['name'] + " exceeded max run, restarting" + "\r\n"
            continue
        if get_last_run_completed(current_instances[i]['name']):
            if liveDelete:
                delete_instance(current_instances[i]['zone'], current_instances[i]['name'])
                response += get_time_string() + "Instance: " + current_instances[i]['name'] + " was deleted" + "\r\n"
            else:
                response += get_time_string() + "Instance: " + current_instances[i]['name'] + " eligible for delete (not exectuted)" + "\r\n"
    if len(response) == 0:
        return get_time_string() + "Nothing to report"
    return response

def StartOrCreateInstance(group, index):
    if not instancesCached:
        _cache_current_instances()
    name = "rasp-blipmap-" + group + "-p-" + str(index)
    if name in current_instances:
        start_instance(current_instances[name]['zone'], name)
        return get_time_string() + "Instance: " + name + " was started" + "\r\n"
    else:
        zone = find_zone()
        if zone:
            create_instance(zone, group, index, name)
            return get_time_string() + "Instance: " + name + " was created & started" + "\r\n"
        else:
            return get_time_string() + "Instance: " + name + " could not be created, no zone available" + "\r\n"

def StopInstance(group, index):
    if not instancesCached:
        _cache_current_instances()
    name = "rasp-blipmap-" + group + "-p-" + str(index)
    if name in current_instances:
        stop_instance(current_instances[name]['zone'], name)
        return get_time_string() + "Instance: " + name + " was stoped" + "\r\n"


def StopAllTrigger():
    if not instancesCached:
        _cache_current_instances()
    response = ""
    for name in current_instances:
        stop_instance(current_instances[name]['zone'], current_instances[name]['name'])
        response += get_time_string() + "Instance: " + name + " was stopped" + "\r\n"
    return


class StartTrigger(webapp2.RequestHandler):
    def get(self, group, index):
        self.response.write(StartOrCreateInstance(group, index))

class StopTrigger(webapp2.RequestHandler):
    def get(self, group, index):
        self.response.write(StopInstance(group, index))

class StatusPage(webapp2.RequestHandler):
    def get(self):
        if not zoneOpsCached:
            _cache_zone_ops()
        status_items = [];
        for i in sorted(recent_instances):
            status_items.append({
                'instance_name': i,
                'instance_status': get_status(i),
                'instance_started': str(get_last_started_time(i)),
                'instance_completed': str(get_last_completed_time(i)),
                'instance_comp_elapsed': str(get_last_run_elapsed(i)),
                'instance_curr_elapsed': str(get_current_run_elapsed(i)),
                'instance_was_preempted': str(get_last_run_preempted(i)),
                'instance_preempted_count': str(get_preemption_count(i)),
                'instance_live': str(get_still_instantance(i))
                })

        data = {}
        data['title'] = "Instance Status"
        data['date'] = datetime.datetime.utcnow()
        data['status_items'] = status_items

        template = jinja_environment.get_template('status.html')
        print template.render(data)
        #self.response.out.write(template.render(data))

app = webapp2.WSGIApplication([
    ('/Start/(.*)/(\d+)',           StartTrigger),
    ('/Stop/(.*)/(\d+)',            StopTrigger),
    ('/StopAll',                    StopAllTrigger),
    ('/Monitor',                    MonitorTrigger),
    ('/',                           StatusPage),
], debug=True)

